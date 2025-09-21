🏥 MediChat — AI-Powered Intelligent Medical Document Query Tool
--------
An AI-powered chatbot interface that enables healthcare professionals to query unstructured medical PDF documents using natural language. Built with AWS services (Bedrock, S3, Elastic Beanstalk), the system transforms PDFs into a knowledge base and provides accurate, contextual answers with source citations.

📌 Features
--------
- Natural Language Search – Ask questions like “What’s the recommended dengue dosage for adults?”
- PDF Knowledge Base – Store, process, and retrieve insights from medical PDFs.
- Chatbot Interface – Gemini/ChatGPT-like UI for intuitive querying.
- Serverless Backend – Deployed via AWS Elastic Beanstalk.
- Secure & Scalable – Built on AWS cloud-native services.

🏗️ System Architecture
--------
<img width="3284" height="2084" alt="image" src="https://github.com/user-attachments/assets/5bf5dee1-021b-427f-8245-3f9b9bbab192" />

Workflow:
1. User interacts via web app (HTML/CSS + API).
2. Elastic Beanstalk hosts the app and connects backend logic.
3. Amazon Bedrock processes queries using:
- Titan Embeddings v2 → semantic search over documents.
- Nova Pro (LLM) → generates precise answers.
4. Knowledge Base references processed documents stored in Amazon S3.
5. Answers are displayed in the chat interface.

🛠️ Tech Stack
--------
| **Component**     | **Technology**                  | 
|-------------------|---------------------------------|
| **Frontend**      | HTML, CSS| 
| **Backend** | Python | 
| **AI & Search** | Amazon Bedrock (Nova Pro, Titan Embeddings v2) | 
| **Storage:** | Amazon S3 (PDF storage) | 
| **Deployment:**      | AWS Elastic Beanstalk  | 

🧑‍💻 Usage
--------
- Open the web app (Elastic Beanstalk URL).
- Upload medical PDFs into S3 bucket.
- Ask questions in the chat interface:
  - “What were the main diagnoses recorded for Mr Tan in the report?”
  - "Who owns the medical records, and who owns the personal information in them?"
- The chatbot retrieves the relevant document sections and generates an answer.
- Version Control: GitHub (CI/CD to Elastic Beanstalk).

