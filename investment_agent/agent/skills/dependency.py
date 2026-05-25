"""Skill 依赖解析：DFS 递归展开、去重、拓扑序、循环检测。"""

from .base import BaseSkill


def resolve_dependencies(
    top_level_names: list[str],
    registry: dict[str, BaseSkill],
) -> list[str]:
    """展开依赖树，返回去重后的拓扑序列表（被依赖的在前）。

    Circular dependencies raise ValueError.
    Missing dependencies are silently skipped.
    """
    resolved: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(
                f"Circular dependency detected: skill '{name}' is part of a cycle"
            )

        skill = registry.get(name)
        if skill is None:
            return

        visiting.add(name)
        for dep_name in skill.depends_on:
            visit(dep_name)
        visiting.discard(name)
        visited.add(name)
        resolved.append(name)

    for name in top_level_names:
        visit(name)

    return resolved


def validate_dependencies(registry: dict[str, BaseSkill]) -> list[str]:
    """校验所有注册 Skill 的 depends_on 引用。返回警告字符串列表。"""
    warnings: list[str] = []

    for skill_name, skill in registry.items():
        if not skill.depends_on:
            continue
        for dep_name in skill.depends_on:
            if dep_name == skill_name:
                warnings.append(
                    f"Skill '{skill_name}' depends on itself"
                )
            elif dep_name not in registry:
                warnings.append(
                    f"Skill '{skill_name}' depends on '{dep_name}', "
                    f"but '{dep_name}' is not registered"
                )

    for skill_name in registry:
        try:
            resolve_dependencies([skill_name], registry)
        except ValueError as exc:
            warnings.append(str(exc))

    return warnings


def expand_with_dependencies(skill_names: list[str]) -> list[str]:
    """展开技能列表，包含 orch 技能的 depends_on 传递依赖。

    复用 resolve_dependencies() 的 DFS 拓扑排序，自动将 orch 技能声明的
    依赖技能加入列表。用于 AccessPolicy 和 _allowed_skill_names 的构建。
    """
    from .loader import _registry, _skills_dir, reload_skills

    if not _registry and _skills_dir:
        reload_skills()
    if not _registry:
        return list(skill_names)
    return resolve_dependencies(skill_names, _registry)
