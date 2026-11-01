from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..adapt.core_bridge import get_locator_elements_payload, get_pipeline_debug_payload
from ..schemas import LocatorElementsRequest, PipelineDebugRequest

router = APIRouter()


@router.post("/locator/elements")
def get_locator_elements_endpoint(payload: LocatorElementsRequest) -> dict:
    try:
        return get_locator_elements_payload(
            original_image_size=(
                payload.original_image_size.model_dump()
                if payload.original_image_size is not None
                else None
            ),
            image_base64=payload.image,
            start_coordinate=payload.start_coordinate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/locator/pipeline-debug")
def pipeline_debug_endpoint(payload: PipelineDebugRequest) -> dict:
    try:
        return get_pipeline_debug_payload(
            image_base64=payload.image,
            action_text=payload.action_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
