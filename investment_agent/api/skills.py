from fastapi import APIRouter

from ..skills.loader import get_all_skills

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills():
    items = []
    for skill in get_all_skills():
        items.append(
            {
                "name": skill.name,
                "description": skill.description,
                "tools": skill.tools,
                "schema_name": skill.schema.get("name", skill.name),
            }
        )
    return items
