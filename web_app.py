# Initiate by running this command: python -m uvicorn app.web_app:app --reload

# Ask a question about the knowledge base:
# http://127.0.0.1:8000/bedrock/query?text=who%20is%20madonna

# Ask a general question:
# http://127.0.0.1:8000/bedrock/invoke?text=who%20is%20madonna

from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import boto3
import os
import json
from dotenv import load_dotenv
import logging
from botocore.exceptions import BotoCoreError, ClientError
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# Retrieve and validate AWS configuration from environment variables
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("MODEL_ID")
KNOWLEDGE_BASE_ID = os.getenv("KNOWLEDGE_BASE_ID")
MODEL_ARN = os.getenv("MODEL_ARN")

# Validate mandatory environment variables
if not AWS_REGION:
    raise ValueError("AWS_REGION environment variable is missing.")

# System prompt to guide the assistant's behavior
SYSTEM_PROMPT = (
    "You are a medical knowledge assistant.\n"
    "Format answers as follows:\n"
    "- When needing to list out the retrieved contents, use bullet points, one sentence per line.\n"
    "- Each point must be concise and on its own line.\n"
    "- Always cite the source with document name."
)

# Pydantic models for request/response
class ChatMessage(BaseModel):
    message: str
    use_knowledge_base: bool = False

app = FastAPI()

# Serve static files like CSS, JS, images
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

# Initialize AWS clients once during application startup
try:
    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    bedrock_agent_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
except (BotoCoreError, ClientError) as e:
    logger.error(f"Failed to initialize AWS clients: {e}")
    raise


def _extract_document_titles_from_citations(rag_response: dict):
    """Best-effort extraction of document titles from Bedrock RAG citations.

    Supports both shapes:
    - { "citations": { "retrievedReferences": [...] }}
    - { "citations": [ { "retrievedReferences": [...] }, ... ] }
    """
    titles = []
    try:
        raw_citations = (rag_response or {}).get("citations", [])
        retrieved_refs = []
        if isinstance(raw_citations, dict):
            retrieved_refs = raw_citations.get("retrievedReferences", [])
        elif isinstance(raw_citations, list):
            for c in raw_citations:
                retrieved_refs.extend((c or {}).get("retrievedReferences", []))
        for ref in retrieved_refs:
            metadata = (ref or {}).get("metadata", {}) or {}
            title = (
                metadata.get("x-amz-bedrock-kb-document-title")
                or metadata.get("x-amzn-bedrock-kb-doc-title")
            )
            if not title:
                location = (ref or {}).get("location", {}) or {}
                s3_uri = (location.get("s3Location", {}) or {}).get("uri")
                web_url = (location.get("webLocation", {}) or {}).get("url")
                uri_or_url = s3_uri or web_url or ""
                if uri_or_url:
                    try:
                        title = os.path.basename(uri_or_url).split("?")[0]
                    except Exception:
                        title = uri_or_url
            if title:
                titles.append(title)
    except Exception:
        pass
    # De-duplicate while preserving order
    seen = set()
    unique_titles = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique_titles.append(t)
    return unique_titles


def _extract_pdf_filenames_from_citations(rag_response: dict):
    """Return only PDF file names from RAG citations (basename like example.pdf).

    Handles both dict and list shapes of the "citations" field.
    """
    filenames = []
    try:
        raw_citations = (rag_response or {}).get("citations", [])
        retrieved_refs = []
        if isinstance(raw_citations, dict):
            retrieved_refs = raw_citations.get("retrievedReferences", [])
        elif isinstance(raw_citations, list):
            for c in raw_citations:
                retrieved_refs.extend((c or {}).get("retrievedReferences", []))
        for ref in retrieved_refs:
            # Prefer explicit locations for reliable file paths
            location = (ref or {}).get("location", {}) or {}
            s3_uri = (location.get("s3Location", {}) or {}).get("uri")
            web_url = (location.get("webLocation", {}) or {}).get("url")
            candidate = s3_uri or web_url or ""
            name = ""
            if candidate:
                try:
                    name = os.path.basename(candidate).split("?")[0]
                except Exception:
                    name = candidate
            # Fallback to metadata fields
            if not name:
                metadata = (ref or {}).get("metadata", {}) or {}
                name = (
                    metadata.get("file_name")
                    or metadata.get("filename")
                    or metadata.get("x-amz-bedrock-kb-document-title")
                    or metadata.get("x-amzn-bedrock-kb-doc-title")
                    or ""
                )
            if name and name.lower().endswith(".pdf"):
                filenames.append(name)
    except Exception:
        pass
    # De-duplicate while preserving order
    seen = set()
    result = []
    for n in filenames:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _format_one_line_bullets(text: str) -> str:
    """Ensure hyphen bullets are one per line, starting with '- '."""
    if not isinstance(text, str) or not text:
        return text
    # Normalize common inline separators to newline bullets
    if " - " in text:
        formatted = text.replace(" - ", "\n- ")
        if not formatted.lstrip().startswith("- "):
            formatted = "- " + formatted.lstrip()
        return formatted
    return text


def _remove_bold_markdown(text: str) -> str:
    """Strip double-asterisk markdown bold markers from text."""
    if not isinstance(text, str) or not text:
        return text
    return text.replace("**", "")


def _finalize_output(body_text: str, pdf_filenames: list | None = None) -> str:
    """Apply bullet formatting, remove bold, and append Sources as a new paragraph.

    Ensures the final output ends with a newline character.
    """
    text = _format_one_line_bullets(body_text or "")
    text = _remove_bold_markdown(text)
    text = text.rstrip()
    if pdf_filenames:
        # Force a paragraph break and a line break using Unicode separators
        paragraph_break = "\u2029\u2028"
        text = f"{text}{paragraph_break}Sources: {', '.join(pdf_filenames)}\n"
    else:
        text = f"{text}\n"
    return text

@app.get("/bedrock/invoke")
async def invoke_model(text: str = Query(..., description="Input text for the model")):
    """
    Endpoint for invoking the model with a system prompt.
    """
    if not MODEL_ID:
        raise HTTPException(status_code=500, detail="MODEL_ID is not configured.")
    
    try:
        # Use Bedrock Converse API to pass a system prompt (works with amazon.nova-pro-v1:0)
        response = bedrock_client.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {"role": "user", "content": [{"text": text}]}
            ],
            inferenceConfig={"maxTokens": 512, "temperature": 0.5},
        )

        # Extract the generated text
        generated_text = ""
        try:
            contents = response["output"]["message"]["content"]
            generated_text = "".join(block.get("text", "") for block in contents)
        except Exception:
            generated_text = ""

        if not generated_text:
            logger.error("Model did not return any content.")
            raise HTTPException(status_code=500, detail="Model did not return any content.")
        
        return {"response": _finalize_output(generated_text)}
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS Client error: {str(e)}")
    except BotoCoreError as e:
        logger.error(f"AWS BotoCoreError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS BotoCore error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.get("/bedrock/query")
async def query_with_knowledge_base(text: str = Query(..., description="Input text for the model")):
    """
    Endpoint for model invocation with knowledge base retrieval and generation.
    """
    if not KNOWLEDGE_BASE_ID or not MODEL_ARN:
        raise HTTPException(status_code=500, detail="Knowledge base configuration is missing.")
    
    try:
        # Include system guidance inline to steer formatting
        input_text = f"{SYSTEM_PROMPT}\n\nUser: {text}"
        response = bedrock_agent_client.retrieve_and_generate(
            input={"text": text},
            retrieveAndGenerateConfiguration={
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                    "modelArn": MODEL_ARN
                },
                "type": "KNOWLEDGE_BASE"
            }
        )
        body = response["output"]["text"]
        pdfs = _extract_pdf_filenames_from_citations(response)
        return {"response": _finalize_output(body, pdfs)}
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise HTTPException(status_code=500, detail="AWS Client error occurred.")
    except BotoCoreError as e:
        logger.error(f"AWS BotoCoreError: {e}")
        raise HTTPException(status_code=500, detail="AWS BotoCore error occurred.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")

@app.post("/chat")
async def chat_endpoint(chat_request: ChatMessage):
    """
    Endpoint for chat interface that handles both general queries and knowledge base queries.
    """
    try:
        if chat_request.use_knowledge_base:
            # Use knowledge base for retrieval
            if not KNOWLEDGE_BASE_ID or not MODEL_ARN:
                raise HTTPException(status_code=500, detail="Knowledge base configuration is missing.")
            
            response = bedrock_agent_client.retrieve_and_generate(
                input={"text": chat_request.message},
                retrieveAndGenerateConfiguration={
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                        "modelArn": MODEL_ARN
                    },
                    "type": "KNOWLEDGE_BASE"
                }
            )
            body = response["output"]["text"]
            pdfs = _extract_pdf_filenames_from_citations(response)
            return {"response": _finalize_output(body, pdfs), "type": "knowledge_base"}
        else:
            # Use regular model invocation
            if not MODEL_ID:
                raise HTTPException(status_code=500, detail="MODEL_ID is not configured.")
            
            # Use Bedrock Converse API with system prompt
            response = bedrock_client.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[
                    {"role": "user", "content": [{"text": chat_request.message}]}
                ],
                inferenceConfig={"maxTokens": 512, "temperature": 0.5},
            )

            # Extract the generated text
            generated_text = ""
            try:
                contents = response["output"]["message"]["content"]
                generated_text = "".join(block.get("text", "") for block in contents)
            except Exception:
                generated_text = ""

            if not generated_text:
                logger.error("Model did not return any content.")
                raise HTTPException(status_code=500, detail="Model did not return any content.")
            
            return {"response": _finalize_output(generated_text), "type": "general"}
    
    except ClientError as e:
        logger.error(f"AWS ClientError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS Client error: {str(e)}")
    except BotoCoreError as e:
        logger.error(f"AWS BotoCoreError: {e}")
        raise HTTPException(status_code=500, detail=f"AWS BotoCore error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
