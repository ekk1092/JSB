import re
from typing import List, Dict, Any

COMMON_SKILLS = [
    "python", "sql", "r", "java", "c++", "javascript", "typescript", "html", "css",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras", "spacy", "nltk",
    "tableau", "power bi", "excel", "spark", "pyspark", "hadoop", "databricks", "snowflake",
    "bigquery", "aws", "azure", "gcp", "docker", "kubernetes", "git", "linux", "bash",
    "airflow", "dbt", "data modeling", "etl", "machine learning", "deep learning",
    "statistics", "a/b testing", "data visualization", "rest api", "fastapi", "flask", "django"
]

JOB_ROLE_KEYWORDS = {
    "Data Analyst": ["analytics", "tableau", "power bi", "excel", "sql", "reporting", "dashboard", "bi"],
    "Data Engineer": ["etl", "pipeline", "spark", "hadoop", "snowflake", "bigquery", "aws", "gcp", "dbt", "airflow", "sql"],
    "Data Scientist": ["machine learning", "statistics", "python", "pandas", "scikit-learn", "modeling", "r", "predictive"],
    "Machine Learning Engineer": ["pytorch", "tensorflow", "deep learning", "mlops", "docker", "fastapi", "deployment"],
    "Software Engineer": ["java", "python", "c++", "javascript", "react", "node", "git", "rest api", "system design"]
}

def analyze_resume_profile(resume_text: str) -> Dict[str, Any]:
    """
    Analyzes raw resume text to extract skills, experience level, and suggested target roles.
    """
    if not resume_text or not resume_text.strip():
        return {
            "skills": [],
            "experience_level": "Entry-Level",
            "suggested_roles": ["Data Analyst", "Data Engineer", "Data Scientist"]
        }

    text_lower = resume_text.lower()

    # Extract matching skills
    found_skills = []
    for skill in COMMON_SKILLS:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, text_lower):
            found_skills.append(skill.title() if len(skill) > 3 else skill.upper())

    # Deduplicate while preserving case
    seen = set()
    unique_skills = []
    for s in found_skills:
        if s.lower() not in seen:
            seen.add(s.lower())
            unique_skills.append(s)

    # Determine experience level
    experience_level = "Entry-Level"
    if any(k in text_lower for k in ["senior", "lead", "staff", "principal", "manager", "5+ years", "6+ years", "7+ years"]):
        experience_level = "Senior-Level"
    elif any(k in text_lower for k in ["mid-level", "3+ years", "4+ years", "experienced"]):
        experience_level = "Mid-Level"
    elif any(k in text_lower for k in ["intern", "internship", "co-op", "student", "graduate"]):
        experience_level = "Entry-Level / Intern"

    # Score suggested roles based on skill overlap
    role_scores = {}
    for role, reqs in JOB_ROLE_KEYWORDS.items():
        score = sum(1 for req in reqs if req in text_lower)
        role_scores[role] = score

    sorted_roles = sorted(role_scores.items(), key=lambda x: x[1], reverse=True)
    suggested_roles = [r[0] for r in sorted_roles[:3]]

    return {
        "skills": unique_skills[:15],
        "experience_level": experience_level,
        "suggested_roles": suggested_roles
    }


def calculate_job_match(resume_text: str, resume_skills: List[str], job_title: str, job_description: str) -> Dict[str, Any]:
    """
    Computes a match score (0-100%), matched skills, and missing skills for a job posting.
    """
    if not job_description and not job_title:
        return {
            "match_percentage": 75,
            "matched_skills": resume_skills[:5],
            "missing_skills": []
        }

    combined_job_text = f"{job_title} {job_description}".lower()
    resume_skills_lower = set(s.lower() for s in resume_skills)

    # Find job requirements from common skills
    job_skills_found = set()
    for skill in COMMON_SKILLS:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, combined_job_text):
            job_skills_found.add(skill.lower())

    if not job_skills_found:
        # Fallback keyword overlap
        job_skills_found = set(w for w in re.findall(r"\b[a-z]{3,}\b", combined_job_text) if len(w) > 3)

    matched = resume_skills_lower.intersection(job_skills_found)
    missing = job_skills_found - resume_skills_lower

    if job_skills_found:
        score = int((len(matched) / max(len(job_skills_found), 1)) * 100)
        # Base boost if resume has solid overlap
        score = min(max(score, 50 if matched else 30), 98)
    else:
        score = 80

    matched_formatted = [s.title() if len(s) > 3 else s.upper() for s in matched]
    missing_formatted = [s.title() if len(s) > 3 else s.upper() for s in missing if s in COMMON_SKILLS]

    return {
        "match_percentage": score,
        "matched_skills": matched_formatted[:6],
        "missing_skills": missing_formatted[:6]
    }
