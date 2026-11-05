"""System endpoints for temporary files and live processing logs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from shared.log_stream import stream_session
from shared.temp_storage import manage_temp_dir

router = APIRouter()


@router.post("/cleanup_temp_files")
async def cleanup_temp_files() -> dict[str, int]:
    deleted_count = manage_temp_dir("all", "delete_all", "all")
    if deleted_count is None:
        raise HTTPException(500, "Не удалось очистить временные папки")
    return {"deleted": deleted_count}


@router.get("/logs/{log_id}")
async def live_logs(log_id: str) -> StreamingResponse:
    return StreamingResponse(
        stream_session(log_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
