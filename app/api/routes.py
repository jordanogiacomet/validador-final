from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.job import JobStatus
from app.core.tenant_loader import load_tenant_config
from app.services.job_service import JobService
from app.services.validation_service import UPLOADS_DIR, run_validation_job

router = APIRouter()

job_service = JobService()


class UploadResponse(BaseModel):
    job_id: str
    status: str
    tenant_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    tenant_id: str
    status: str
    total_rows: int
    rows_with_issues: int
    total_issues: int
    error_message: str | None = None


@router.post("/validate", response_model=UploadResponse)
async def upload_and_validate(
    file: UploadFile,
    tenant_id: str = "default",
    background_tasks: BackgroundTasks = BackgroundTasks(),  # noqa: B008
) -> UploadResponse:
    try:
        load_tenant_config(tenant_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Tenant not found: {tenant_id}"
        ) from None

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    job = job_service.create_job(tenant_id=tenant_id)
    file_path = UPLOADS_DIR / f"{job.job_id}_{file.filename}"

    content = await file.read()
    file_path.write_bytes(content)

    job.file_path = str(file_path)

    background_tasks.add_task(run_validation_job, job.job_id, job_service)

    return UploadResponse(
        job_id=job.job_id,
        status=job.status.value,
        tenant_id=job.tenant_id,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatusResponse(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        status=job.status.value,
        total_rows=job.total_rows,
        rows_with_issues=job.rows_with_issues,
        total_issues=job.total_issues,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}/result")
async def download_result(job_id: str) -> dict:
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not completed: {job.status.value}")

    if not job.result_path or not Path(job.result_path).exists():
        raise HTTPException(status_code=404, detail="Result file not found")

    import json

    return json.loads(Path(job.result_path).read_text())


@router.get("/jobs/{job_id}/report")
async def download_report(job_id: str):
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Job not completed: {job.status.value}")

    if not job.report_path or not Path(job.report_path).exists():
        raise HTTPException(status_code=404, detail="Report file not found")

    from fastapi.responses import FileResponse

    return FileResponse(
        path=job.report_path,
        media_type="application/pdf",
        filename=f"report_{job_id}.pdf",
    )
