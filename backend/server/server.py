import json
import os
from typing import Dict, List, Optional
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, File, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.server.websocket_manager import WebSocketManager
from backend.server.server_utils import (
    get_config_dict, sanitize_filename,
    update_environment_variables, handle_file_upload, handle_file_deletion,
    execute_multi_agents, handle_websocket_communication
)

from backend.server.websocket_manager import run_agent
from backend.utils import write_md_to_word, write_md_to_pdf, write_text_to_md
from gpt_researcher.utils.logging_config import setup_research_logging
from gpt_researcher.utils.enum import Tone

import logging

# Get logger instance
logger = logging.getLogger(__name__)

# Don't override parent logger settings
logger.propagate = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Only log to console
    ]
)

# Models


class ResearchRequest(BaseModel):
    task: str
    report_type: str
    report_source: str
    tone: str
    headers: dict | None = None
    repo_name: str
    branch_name: str
    generate_in_background: bool = True


class ConfigRequest(BaseModel):
    ANTHROPIC_API_KEY: str
    TAVILY_API_KEY: str
    LANGCHAIN_TRACING_V2: str
    LANGCHAIN_API_KEY: str
    OPENAI_API_KEY: str
    DOC_PATH: str
    RETRIEVER: str
    GOOGLE_API_KEY: str = ''
    GOOGLE_CX_KEY: str = ''
    BING_API_KEY: str = ''
    SEARCHAPI_API_KEY: str = ''
    SERPAPI_API_KEY: str = ''
    SERPER_API_KEY: str = ''
    SEARX_URL: str = ''
    XAI_API_KEY: str
    DEEPSEEK_API_KEY: str


# App initialization
app = FastAPI()

# Static files and templates
app.mount("/site", StaticFiles(directory="./frontend"), name="site")
app.mount("/static", StaticFiles(directory="./frontend/static"), name="static")
templates = Jinja2Templates(directory="./frontend")

# WebSocket manager
manager = WebSocketManager()

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
DOC_PATH = os.getenv("DOC_PATH", "./my-docs")

# Startup event


@app.on_event("startup")
def startup_event():
    os.makedirs("outputs", exist_ok=True)
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")
    # os.makedirs(DOC_PATH, exist_ok=True)  # Commented out to avoid creating the folder if not needed
    

# Routes


@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "report": None})


@app.get("/report/{research_id}")
async def read_report(request: Request, research_id: str, file_type: str = "docx"):
    """
    Returns the requested report file (docx, pdf, or md) based on the file_type parameter.
    """
    # Validate the file type
    file_extension = file_type.lower()
    if file_extension not in ["docx", "pdf", "md"]:
        return {"message": "Invalid file type. Supported types are: docx, pdf, md."}

    # Construct the file path
    file_path = os.path.join('outputs', f"{research_id}.{file_extension}")
    if not os.path.exists(file_path):
        return {"message": f"Report with {file_extension} format not found."}

    # Return the file
    return FileResponse(file_path)


async def write_report(research_request: ResearchRequest, research_id: str = None):
    if not research_id:
        raise ValueError("research_id must be provided")

    try:
        # Генерация отчета
        report_information = await run_agent(
            task=research_request.task,
            report_type=research_request.report_type,
            report_source=research_request.report_source,
            source_urls=[],
            document_urls=[],
            tone=Tone[research_request.tone],
            websocket=None,
            stream_output=None,
            headers=research_request.headers,
            query_domains=[],
            config_path="",
            return_researcher=True
        )

        # Сохранение файлов
        docx_path = await write_md_to_word(report_information[0], research_id)
        pdf_path = await write_md_to_pdf(report_information[0], research_id)
        md_path = await write_text_to_md(report_information[0], research_id)  # Save as Markdown

    except Exception as e:
        logger.error(f"Error while generating report: {e}")
        raise ValueError("Failed to generate report. Please try again later.")

    if research_request.report_type != "multi_agents":
        report, researcher = report_information
        response = {
            "research_id": research_id,
            "research_information": {
                "source_urls": researcher.get_source_urls(),
                "research_costs": researcher.get_costs(),
                "visited_urls": list(researcher.visited_urls),
                "research_images": researcher.get_research_images(),
            },
            "report": report,
            "docx_path": docx_path,
            "pdf_path": pdf_path
        }
    else:
        response = {"research_id": research_id, "report": "", "docx_path": docx_path, "pdf_path": pdf_path}

    return response

@app.post("/report/")
async def generate_report(
    research_request: ResearchRequest,
    background_tasks: BackgroundTasks,
    research_id: Optional[str] = None
):
    # Если research_id не передан, генерируем его автоматически
    research_id = research_id or f"task_{int(time.time())}_{research_request.task}"

    if research_request.generate_in_background:
        background_tasks.add_task(write_report, research_request=research_request, research_id=research_id)
        return {
            "message": "Your report is being generated in the background. Please check back later.",
            "research_id": research_id
        }
    else:
        response = await write_report(research_request, research_id)
        return response

@app.get("/reports/status")
async def get_reports_status():
    """
    Returns the status of all reports:
    - Completed reports (.docx, .pdf, and .md)
    - In-progress reports (.json)
    """
    if not os.path.exists("outputs"):
        return {"message": "No reports found."}

    files = os.listdir("outputs")
    completed_reports = []
    in_progress_reports = []

    for file in files:
        file_path = os.path.join("outputs", file)
        if not os.path.isfile(file_path):
            continue  # Skip if it's not a file
        if file.endswith(".docx") or file.endswith(".pdf") or file.endswith(".md"):
            completed_reports.append(file)
        elif file.endswith(".json"):
            in_progress_reports.append(file)

    return {
        "completed_reports": completed_reports,
        "in_progress_reports": in_progress_reports
    }

@app.get("/files/")
async def list_files():
    if not os.path.exists(DOC_PATH):
        os.makedirs(DOC_PATH, exist_ok=True)
    files = os.listdir(DOC_PATH)
    print(f"Files in {DOC_PATH}: {files}")
    return {"files": files}


@app.post("/api/multi_agents")
async def run_multi_agents():
    return await execute_multi_agents(manager)


@app.post("/upload/")
async def upload_file(file: UploadFile = File(...)):
    return await handle_file_upload(file, DOC_PATH)

@app.delete("/reports/clear")
async def clear_all_reports():
    """
    Deletes all reports (both completed and in-progress) from the 'outputs' directory.
    """
    if not os.path.exists("outputs"):
        return {"message": "No reports to delete."}

    files = os.listdir("outputs")
    errors = []

    for file in files:
        try:
            await handle_file_deletion(file, "outputs")
        except Exception as e:
            logger.error(f"Failed to delete file {file}: {e}")
            errors.append(file)

    if errors:
        return {
            "message": "Some files could not be deleted.",
            "failed_files": errors
        }

    return {"message": "All reports have been deleted."}

@app.delete("/files/{filename}")
async def delete_file(filename: str):
    return await handle_file_deletion(filename, DOC_PATH)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await handle_websocket_communication(websocket, manager)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
