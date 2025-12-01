import os
from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

def get_azure_client():
    return AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )

def tailor_resume_tool(resume_text: str, job_description: str) -> str:
    """
    Tailors a resume for a specific job description using Azure OpenAI.
    """
    client = get_azure_client()
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    prompt = f"""
    You are an expert career coach and resume writer.
    
    JOB DESCRIPTION:
    {job_description}
    
    CURRENT RESUME:
    {resume_text}
    
    Task: Rewrite the resume to better match the job description. 
    Highlight relevant skills and experiences. 
    Keep the format clean and professional (Markdown).
    Do not invent experiences, but rephrase existing ones to match keywords.
    """

    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content

def generate_cover_letter_tool(resume_text: str, job_description: str) -> str:
    """
    Generates a cover letter based on a resume and job description using Azure OpenAI.
    """
    client = get_azure_client()
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

    prompt = f"""
    You are an expert career coach.
    
    JOB DESCRIPTION:
    {job_description}
    
    RESUME:
    {resume_text}
    
    Task: Write a compelling, professional cover letter for this job application.
    The tone should be enthusiastic but professional.
    Use Markdown format.
    """

    response = client.chat.completions.create(
        model=deployment_name,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content
