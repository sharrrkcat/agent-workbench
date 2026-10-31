"""Read-only QQ check reports; never invoke or load a model."""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from ai_workbench import __version__
from ai_workbench.core.time import isoformat_utc
from ai_workbench.db.qq_models import QQBatch, QQMessage


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")


def latest_context(state, store, session_id, profile):
    before = None
    while True:
        with Session(store.engine) as db:
            query = select(QQBatch.id, QQBatch.run_id).where(QQBatch.session_id == session_id, QQBatch.run_id.is_not(None))
            if before is not None:
                query = query.where(QQBatch.id < before)
            rows = db.exec(query.order_by(QQBatch.id.desc()).limit(32)).all()
        if not rows:
            return "最近模型调用：暂无"
        for row in rows:
            steps = state.runs.list_steps(row.run_id)
            completed = [step for step in steps if step.kind == "model" and step.status not in {"pending", "running"}]
            if not completed:
                continue
            step = max(completed, key=lambda item: item.order)
            budget = step.metadata.get("context", {}).get("budget")
            call = step.metadata.get("llm", {})
            if not budget or profile is None or call.get("model_profile_id") != profile.id or (
                    budget.get("configured_window_tokens") != profile.context_window_tokens):
                return "最近模型调用：暂无（当前模型配置）"
            usage = call.get("usage") or {}
            counts = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
            used = "暂无" if None in counts else str(sum(counts))
            when = step.finished_at or step.updated_at
            return (f"最近模型调用：{isoformat_utc(when)}\n"
                f"上下文用量：{used} / {budget['window_tokens']} tokens；裁剪 {budget['removed_turns']} 轮")
        before = rows[-1].id


def check_report(service, binding, resources):
    state, store = service.state, service.store
    project = state.projects.get(binding.project_id)
    # These bounded reads also establish database health without loading all Sessions.
    with Session(store.engine) as db:
        queued = db.exec(select(func.count()).select_from(QQBatch).where(
            QQBatch.session_id == binding.session_id, QQBatch.status == "queued")).one()
        pending = db.exec(select(func.count()).select_from(QQMessage).where(
            QQMessage.session_id == binding.session_id, QQMessage.kind == "chat",
            QQMessage.disposition == "pending", QQMessage.deleted == False)).one()
    active = store.active_batch(binding.session_id)
    status = "已暂停" if binding.paused else "运行中" if active else "空闲"
    if binding.paused:
        status += f"（{binding.pause_reason}）"
    profile = state.model_manager.profile(project.model_profile_id, "llm") if project.model_profile_id else None
    model_status = state.model_manager.status(profile.id).state if profile else "未配置"
    connection = service.connections.get(project.id)
    connection_status = connection.status if connection else "connecting" if project.connection_enabled else "disabled"
    memory, process, cpu = resources["memory"], resources["process"], resources["cpu"]

    def mib(value):
        return "暂无" if value is None else f"{value / 1024 / 1024:.1f} MiB"

    def percent(value):
        return "暂无" if value is None else f"{value:.1f}%"

    policy = project.context_policy
    limit = lambda value: "不限" if value is None else str(value)
    return "\n".join([
        f"Cogita {__version__} · health: ok · 数据库: ok",
        f"活动任务：{state.active_runs.active_count()}",
        f"后端 RSS：{mib(process.get('backend_memory_bytes'))}",
        f"主机内存：{mib(memory.get('used_bytes'))} / {mib(memory.get('total_bytes'))}（{percent(memory.get('percent'))}）",
        f"CPU：{percent(cpu.get('percent'))}",
        f"会话：{binding.target_kind}:{binding.target_id} · {status}",
        f"当前任务：{active.run_id or '准备中' if active else '无'}；待执行批次：{queued}；待聚合消息：{pending}",
        f"上下文限制：{limit(policy.max_messages)} 条 / {limit(policy.max_chars)} 字符",
        latest_context(state, store, binding.session_id, profile),
        f"NapCat：{connection_status}；机器人：{project.bot_account}",
        f"模型：{profile.alias if profile else '未配置'} · {model_status}（本地状态，未发起推理探测）",
    ])
