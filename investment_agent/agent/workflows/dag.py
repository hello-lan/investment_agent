"""Workflow DAG 校验辅助。"""

from __future__ import annotations

from collections import deque

from .schema import WorkflowSpec


def validate_workflow_spec(spec: WorkflowSpec) -> WorkflowSpec:
    """校验 workflow 的 DAG 合法性。"""
    nodes = spec.nodes
    ids = [node.id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("workflow 节点 id 不能重复")

    node_map = {node.id: node for node in nodes}
    for node in nodes:
        if node.id in node.depends_on or node.id in node.input_from:
            raise ValueError(f"节点 {node.id} 不能依赖自身")
        for ref in [*node.depends_on, *node.input_from]:
            if ref not in node_map:
                raise ValueError(f"节点 {node.id} 引用了不存在的上游节点: {ref}")
        if node.type == "delegate" and not node.skill_names:
            raise ValueError(f"delegate 节点 {node.id} 必须提供 skill_names")
        if node.type == "subagent" and not node.targets:
            raise ValueError(f"subagent 节点 {node.id} 必须提供 targets")

    topological_order(spec)
    return spec


def topological_order(spec: WorkflowSpec) -> list[str]:
    """返回拓扑序；若存在环则抛错。"""
    node_map = {node.id: node for node in spec.nodes}
    indegree: dict[str, int] = {node.id: 0 for node in spec.nodes}
    graph: dict[str, list[str]] = {node.id: [] for node in spec.nodes}

    for node in spec.nodes:
        deps = set(node.depends_on) | set(node.input_from)
        indegree[node.id] = len(deps)
        for dep in deps:
            graph.setdefault(dep, []).append(node.id)

    queue = deque(sorted([node_id for node_id, deg in indegree.items() if deg == 0]))
    ordered: list[str] = []

    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for nxt in sorted(graph.get(node_id, [])):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(spec.nodes):
        raise ValueError("workflow 存在循环依赖，无法形成 DAG")
    return ordered
