import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from app.models.schemas import (
    AdaptationResponse,
    AdaptationRow,
    BusinessConfigResponse,
    FullSystemResponse,
    KnowledgeBaseConfig,
    NetworkConfig,
    NetworkConfigResponse,
    PerformanceEvaluateResponse,
    ResourceAllocationResponseV2,
    SliceConfigRequest,
    SliceConfigResponse,
    UserBusinessItem,
    UserResourceAllocation,
)
from app.services.semantic_service import build_network_config
from app.services.slicing_service import build_slice_config
from app.store.database import connection_scope


DEFAULT_USERS = (
    ("admin", "admin123", "admin"),
    ("user1", "user123", "user"),
    ("user2", "user123", "user"),
)

PASS_SIM_THRESHOLD = 0.60
PASS_DELAY_THRESHOLD_MS = 130.0
SLICE_COUNT = 3


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_password(raw_password: str) -> str:
    return hashlib.sha256(str(raw_password or "").encode("utf-8")).hexdigest()


def verify_password(raw_password: str, stored_hash: str) -> bool:
    return hash_password(raw_password) == str(stored_hash or "")


def seed_default_users() -> None:
    with connection_scope() as conn:
        for username, password, role in DEFAULT_USERS:
            row = conn.execute("SELECT id FROM user_account WHERE username = ?", (username,)).fetchone()
            if row:
                continue
            created_at = now_iso()
            conn.execute(
                """
                INSERT INTO user_account (username, password_hash, role, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (username, hash_password(password), role, created_at, created_at),
            )


def get_user_by_username(username: str) -> Optional[Dict[str, object]]:
    with connection_scope() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, role, status, created_at, updated_at FROM user_account WHERE username = ?",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    created_at = now_iso()
    expired_at = (datetime.now() + timedelta(days=7)).isoformat(timespec="seconds")
    with connection_scope() as conn:
        conn.execute(
            """
            INSERT INTO auth_session (user_id, token, status, expired_at, created_at, last_access_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (int(user_id), token, expired_at, created_at, created_at),
        )
    return token


def delete_session(token: str) -> None:
    with connection_scope() as conn:
        conn.execute("UPDATE auth_session SET status = 'inactive' WHERE token = ?", (token,))


def get_session_user(token: str) -> Optional[Dict[str, object]]:
    with connection_scope() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.token AS token,
                s.status AS session_status,
                s.expired_at AS expired_at,
                u.id AS user_id,
                u.username AS username,
                u.role AS role,
                u.status AS user_status
            FROM auth_session s
            JOIN user_account u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("session_status") != "active" or result.get("user_status") != "active":
            return None
        expired_at = result.get("expired_at")
        if expired_at and str(expired_at) < now_iso():
            conn.execute("UPDATE auth_session SET status = 'inactive' WHERE token = ?", (token,))
            return None
        conn.execute(
            "UPDATE auth_session SET last_access_at = ? WHERE token = ?",
            (now_iso(), token),
        )
    return {
        "user_id": int(result["user_id"]),
        "username": str(result["username"]),
        "role": str(result["role"]),
    }


def get_auth_stats() -> Dict[str, object]:
    with connection_scope() as conn:
        session_count = conn.execute(
            "SELECT COUNT(*) AS c FROM auth_session WHERE status = 'active'"
        ).fetchone()["c"]
        user_rows = conn.execute(
            """
            SELECT DISTINCT u.username
            FROM auth_session s
            JOIN user_account u ON u.id = s.user_id
            WHERE s.status = 'active'
            ORDER BY u.username
            """
        ).fetchall()
    active_users = [str(row["username"]) for row in user_rows]
    return {
        "active_session_count": int(session_count),
        "active_user_count": len(active_users),
        "active_users": active_users,
    }


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Optional[str], default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def save_network_config(config: NetworkConfig, created_by_user_id: Optional[int]) -> int:
    created_at = now_iso()
    with connection_scope() as conn:
        conn.execute("UPDATE network_config SET is_active = 0 WHERE is_active = 1")
        cursor = conn.execute(
            """
            INSERT INTO network_config (
                total_bandwidth, total_power, target_snr_db, node_count, base_station_count, channel_scenario,
                is_active, created_by_user_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                float(config.total_bandwidth),
                float(config.total_power),
                float(config.target_snr_db),
                int(config.node_count),
                int(config.base_station_count),
                str(config.channel_scenario or ""),
                int(created_by_user_id) if created_by_user_id is not None else None,
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def save_slice_config(config: SliceConfigRequest, created_by_user_id: Optional[int]) -> int:
    created_at = now_iso()
    knowledge_rows = [
        {
            "kb_id": item.kb_id,
            "kb_type": item.kb_type,
            "knowledge_level": float(item.knowledge_level),
        }
        for item in config.knowledge_bases
    ]
    with connection_scope() as conn:
        conn.execute("UPDATE slice_config SET is_active = 0 WHERE is_active = 1")
        cursor = conn.execute(
            """
            INSERT INTO slice_config (
                slice_count, slice_names_json, codec_count, codec_modality,
                knowledge_bases_json, is_active, created_by_user_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                int(config.slice_count),
                _json_dumps(list(config.slice_names)),
                int(config.codec_count),
                str(config.codec_modality),
                _json_dumps(knowledge_rows),
                int(created_by_user_id) if created_by_user_id is not None else None,
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def get_active_network_record() -> Optional[Dict[str, object]]:
    with connection_scope() as conn:
        row = conn.execute(
            """
            SELECT id, total_bandwidth, total_power, target_snr_db, node_count, base_station_count, channel_scenario,
                   is_active, created_by_user_id, created_at
            FROM network_config
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_active_slice_record() -> Optional[Dict[str, object]]:
    with connection_scope() as conn:
        row = conn.execute(
            """
            SELECT id, slice_count, slice_names_json, codec_count, codec_modality,
                   knowledge_bases_json, is_active, created_by_user_id, created_at
            FROM slice_config
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def network_model_from_record(record: Dict[str, object]) -> NetworkConfig:
    return NetworkConfig(
        total_bandwidth=float(record["total_bandwidth"]),
        total_power=float(record["total_power"]),
        target_snr_db=float(record.get("target_snr_db") or 6.0),
        node_count=int(record.get("node_count") or 5),
        base_station_count=int(record.get("base_station_count") or 1),
        channel_scenario=str(record.get("channel_scenario") or ""),
    )


def slice_request_from_record(record: Dict[str, object]) -> SliceConfigRequest:
    knowledge_bases = [
        KnowledgeBaseConfig(**item)
        for item in _json_loads(record.get("knowledge_bases_json"), [])
    ]
    return SliceConfigRequest(
        slice_count=int(record["slice_count"]),
        slice_names=list(_json_loads(record.get("slice_names_json"), [])),
        codec_count=int(record["codec_count"]),
        codec_modality=str(record["codec_modality"]),
        knowledge_bases=knowledge_bases,
    )


def active_network_response() -> Optional[Tuple[int, NetworkConfig, NetworkConfigResponse]]:
    record = get_active_network_record()
    if record is None:
        return None
    config = network_model_from_record(record)
    return int(record["id"]), config, build_network_config(config)


def active_slice_response() -> Optional[Tuple[int, SliceConfigRequest, SliceConfigResponse]]:
    record = get_active_slice_record()
    if record is None:
        return None
    request = slice_request_from_record(record)
    return int(record["id"]), request, build_slice_config(request)


def create_task_submission(owner_user_id: int, business_output: BusinessConfigResponse) -> Tuple[int, Dict[str, int]]:
    created_at = now_iso()
    with connection_scope() as conn:
        cursor = conn.execute(
            """
            INSERT INTO task_submission (user_id, status, created_at, updated_at)
            VALUES (?, 'running', ?, ?)
            """,
            (int(owner_user_id), created_at, created_at),
        )
        submission_id = int(cursor.lastrowid)
        task_map: Dict[str, int] = {}
        for item in business_output.users:
            task_cursor = conn.execute(
                """
                INSERT INTO task_item (
                    submission_id, biz_user_code, requirement_type, domain_type,
                    payload_symbols, distance_m, base_similarity, task_pkl, task_vocab, sample_index, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    str(item.user_id),
                    str(item.requirement_type),
                    str(item.domain_type),
                    int(item.payload_symbols),
                    float(item.distance_m),
                    float(item.base_similarity),
                    item.task_pkl,
                    item.task_vocab,
                    int(getattr(item, "sample_index", 0)),
                    created_at,
                ),
            )
            task_map[str(item.user_id)] = int(task_cursor.lastrowid)
        return submission_id, task_map


def update_task_submission_status(submission_id: int, status: str) -> None:
    with connection_scope() as conn:
        conn.execute(
            "UPDATE task_submission SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), now_iso(), int(submission_id)),
        )


def create_workflow_run(
    submission_id: int,
    network_config_id: int,
    slice_config_id: int,
    allocation_algorithm: str,
    adaptation_method: str,
) -> int:
    started_at = now_iso()
    with connection_scope() as conn:
        cursor = conn.execute(
            """
            INSERT INTO workflow_run (
                submission_id, network_config_id, slice_config_id,
                allocation_algorithm, adaptation_method, run_status,
                started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, 'running', ?, NULL)
            """,
            (
                int(submission_id),
                int(network_config_id),
                int(slice_config_id),
                str(allocation_algorithm),
                str(adaptation_method),
                started_at,
            ),
        )
        return int(cursor.lastrowid)


def complete_workflow_run(run_id: int, performance_output: PerformanceEvaluateResponse, run_status: str = "success") -> None:
    core = performance_output.core_metrics or {}
    with connection_scope() as conn:
        conn.execute(
            """
            UPDATE workflow_run
            SET run_status = ?, avg_fidelity = ?, avg_delay_ms = ?, avg_s_se = ?, finished_at = ?
            WHERE id = ?
            """,
            (
                str(run_status),
                float(core.get("avg_fidelity", 0.0)),
                float(core.get("avg_delay_ms", 0.0)),
                float(core.get("avg_s_se", 0.0)),
                now_iso(),
                int(run_id),
            ),
        )


def persist_run_results(
    run_id: int,
    task_item_map: Dict[str, int],
    adaptation_output: AdaptationResponse,
    allocation_output: ResourceAllocationResponseV2,
    performance_output: PerformanceEvaluateResponse,
) -> None:
    alloc_map = {item.user_id: item for item in allocation_output.allocations}
    perf_map = {str(item.get("user_id")): item for item in performance_output.user_metrics}

    with connection_scope() as conn:
        for row in adaptation_output.relations:
            task_item_id = task_item_map.get(str(row.user_id))
            if task_item_id is None:
                continue
            conn.execute(
                """
                INSERT INTO adaptation_result (
                    run_id, task_item_id, matched_slice_id, matched_slice_name,
                    codec_id, kb_id, similarity_score
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    int(task_item_id),
                    str(row.matched_slice_id),
                    str(row.matched_slice_name),
                    str(row.codec_id),
                    str(row.kb_id),
                    float(row.similarity_score),
                ),
            )

        for user_id, row in alloc_map.items():
            task_item_id = task_item_map.get(str(user_id))
            if task_item_id is None:
                continue
            conn.execute(
                """
                INSERT INTO allocation_result (
                    run_id, task_item_id, slice_id, bandwidth, power
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    int(task_item_id),
                    str(row.slice_id),
                    float(row.bandwidth),
                    float(row.power),
                ),
            )

        for user_id, row in perf_map.items():
            task_item_id = task_item_map.get(str(user_id))
            if task_item_id is None:
                continue
            conn.execute(
                """
                INSERT INTO performance_result (
                    run_id, task_item_id, slice_id, fidelity, delay_ms,
                    snr_db, similarity_score, knowledge_factor, s_se, pass,
                    source_text, encoded_signal_shape, encoded_signal_preview, decoded_text, token_match_rate,
                    sample_index, task_pkl, task_vocab, model_profile,
                    checkpoint_name, decode_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    int(task_item_id),
                    str(row.get("slice_id", "")),
                    float(row.get("fidelity", 0.0)),
                    float(row.get("delay_ms", 0.0)),
                    float(row.get("snr_db", 0.0)),
                    float(row.get("similarity_score", 0.0)),
                    float(row.get("knowledge_factor", 0.0)),
                    float(row.get("s_se", 0.0)),
                    1 if row.get("pass", False) else 0,
                    str(row.get("source_text", "")),
                    str(row.get("encoded_signal_shape", "")),
                    str(row.get("encoded_signal_preview", "")),
                    str(row.get("decoded_text", "")),
                    float(row.get("token_match_rate", row.get("fidelity", 0.0))),
                    int(row.get("sample_index", 0) or 0),
                    str(row.get("task_pkl", "")),
                    str(row.get("task_vocab", "")),
                    str(row.get("model_profile", "")),
                    str(row.get("checkpoint_name", "")),
                    str(row.get("decode_error", "")),
                ),
            )


def save_strategy_compare_summary(submission_id: int, strategy: str, performance_output: PerformanceEvaluateResponse) -> None:
    user_metrics = performance_output.user_metrics or []
    core = performance_output.core_metrics or {}
    avg_ss = 0.0
    avg_s_se = 0.0
    if user_metrics:
        avg_ss = float(sum(float(item.get("fidelity", 0.0)) for item in user_metrics) / len(user_metrics))
        avg_s_se = float(core.get("avg_s_se", 0.0))
        if avg_s_se == 0.0:
            avg_s_se = float(sum(float(item.get("s_se", 0.0)) for item in user_metrics) / len(user_metrics))

    with connection_scope() as conn:
        conn.execute(
            "DELETE FROM strategy_compare_summary WHERE submission_id = ? AND strategy = ?",
            (int(submission_id), str(strategy)),
        )
        conn.execute(
            """
            INSERT INTO strategy_compare_summary (
                submission_id, strategy, avg_delay_ms, avg_ss, avg_s_se, task_count, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(submission_id),
                str(strategy),
                float(core.get("avg_delay_ms", 0.0)),
                float(avg_ss),
                float(avg_s_se),
                int(len(user_metrics)),
                now_iso(),
            ),
        )


def get_latest_submission_id(owner_user_id: Optional[int] = None) -> Optional[int]:
    query = "SELECT id FROM task_submission"
    params: Tuple[object, ...] = ()
    if owner_user_id is not None:
        query += " WHERE user_id = ?"
        params = (int(owner_user_id),)
    query += " ORDER BY id DESC LIMIT 1"
    with connection_scope() as conn:
        row = conn.execute(query, params).fetchone()
    return int(row["id"]) if row else None


def _load_submission_rows(submission_id: int) -> Tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
    with connection_scope() as conn:
        submission_row = conn.execute(
            "SELECT id, user_id, status, created_at, updated_at FROM task_submission WHERE id = ?",
            (int(submission_id),),
        ).fetchone()
        task_rows = conn.execute(
            """
            SELECT id, submission_id, biz_user_code, requirement_type, domain_type,
                   payload_symbols, distance_m, base_similarity, task_pkl, task_vocab, sample_index, created_at
            FROM task_item
            WHERE submission_id = ?
            ORDER BY id ASC
            """,
            (int(submission_id),),
        ).fetchall()
    return (dict(submission_row) if submission_row else None, [dict(row) for row in task_rows])


def _load_run_rows(submission_id: int) -> List[Dict[str, object]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT id, submission_id, network_config_id, slice_config_id, allocation_algorithm,
                   adaptation_method, run_status, avg_fidelity, avg_delay_ms, avg_s_se,
                   started_at, finished_at
            FROM workflow_run
            WHERE submission_id = ?
            ORDER BY id DESC
            """,
            (int(submission_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _build_business_output_from_task_rows(task_rows: List[Dict[str, object]]) -> BusinessConfigResponse:
    users = [
        UserBusinessItem(
            user_id=str(row["biz_user_code"]),
            modality="text",
            requirement_type=str(row["requirement_type"]),
            domain_type=str(row["domain_type"]),
            payload_symbols=int(row["payload_symbols"]),
            distance_m=float(row["distance_m"]),
            base_similarity=float(row["base_similarity"]),
            task_pkl=row.get("task_pkl"),
            task_vocab=row.get("task_vocab"),
            sample_index=int(row.get("sample_index") or 0),
        )
        for row in task_rows
    ]
    summary = {
        "user_count": len(users),
        "modality": "text",
        "high_fidelity_count": sum(1 for item in users if item.requirement_type == "high_fidelity"),
        "low_latency_count": sum(1 for item in users if item.requirement_type == "low_latency"),
    }
    return BusinessConfigResponse(users=users, summary=summary)


def _derived_pass(requirement_type: str, fidelity: float, delay_ms: float) -> bool:
    value = str(requirement_type or "").strip().lower()
    if value in {"rt", "low_latency"}:
        return float(delay_ms) <= PASS_DELAY_THRESHOLD_MS
    if value in {"hf", "high_fidelity"}:
        return float(fidelity) >= PASS_SIM_THRESHOLD
    return float(fidelity) >= 0.55 and float(delay_ms) <= 180.0


def _build_allocation_metrics(
    allocations: List[UserResourceAllocation],
    network: NetworkConfig,
    allocation_algorithm: str = "semslice",
) -> Tuple[Dict[str, float], Dict[str, float], List[Dict[str, float]]]:
    used_bw = 0.0
    used_power = 0.0
    timeline: List[Dict[str, float]] = []
    seen_slices = set()

    if str(allocation_algorithm or "").strip().lower() == "noslice":
        used_bw = max((float(item.bandwidth) for item in allocations), default=0.0)
        used_power = max((float(item.power) for item in allocations), default=0.0)
        if allocations:
            used_bw = min(float(network.total_bandwidth), used_bw * SLICE_COUNT)
            used_power = min(float(network.total_power), used_power * SLICE_COUNT)
        for step, _ in enumerate(allocations):
            timeline.append(
                {
                    "step": float(step + 1),
                    "used_bandwidth": round(used_bw, 5),
                    "used_power": round(used_power, 5),
                    "remaining_bandwidth": round(max(0.0, float(network.total_bandwidth) - used_bw), 5),
                    "remaining_power": round(max(0.0, float(network.total_power) - used_power), 5),
                }
            )
        return (
            {
                "bandwidth": round(used_bw, 5),
                "power": round(used_power, 5),
            },
            {
                "bandwidth": round(max(0.0, float(network.total_bandwidth) - used_bw), 5),
                "power": round(max(0.0, float(network.total_power) - used_power), 5),
            },
            timeline,
        )

    for step, item in enumerate(allocations):
        if item.slice_id not in seen_slices:
            used_bw += float(item.bandwidth)
            used_power += float(item.power)
            seen_slices.add(item.slice_id)
        timeline.append(
            {
                "step": float(step + 1),
                "used_bandwidth": round(used_bw, 5),
                "used_power": round(used_power, 5),
                "remaining_bandwidth": round(max(0.0, float(network.total_bandwidth) - used_bw), 5),
                "remaining_power": round(max(0.0, float(network.total_power) - used_power), 5),
            }
        )

    used_resources = {
        "bandwidth": round(used_bw, 5),
        "power": round(used_power, 5),
    }
    remaining_resources = {
        "bandwidth": round(max(0.0, float(network.total_bandwidth) - used_bw), 5),
        "power": round(max(0.0, float(network.total_power) - used_power), 5),
    }
    return used_resources, remaining_resources, timeline


def build_full_system_response(run_id: int) -> Optional[FullSystemResponse]:
    with connection_scope() as conn:
        run_row = conn.execute(
            """
            SELECT id, submission_id, network_config_id, slice_config_id, allocation_algorithm,
                   adaptation_method, run_status, avg_fidelity, avg_delay_ms, avg_s_se,
                   started_at, finished_at
            FROM workflow_run
            WHERE id = ?
            """,
            (int(run_id),),
        ).fetchone()
        if run_row is None:
            return None

        run_record = dict(run_row)
        submission_row = conn.execute(
            "SELECT id, user_id, status, created_at, updated_at FROM task_submission WHERE id = ?",
            (int(run_record["submission_id"]),),
        ).fetchone()
        task_rows = conn.execute(
            """
            SELECT id, submission_id, biz_user_code, requirement_type, domain_type,
                   payload_symbols, distance_m, base_similarity, task_pkl, task_vocab, sample_index, created_at
            FROM task_item
            WHERE submission_id = ?
            ORDER BY id ASC
            """,
            (int(run_record["submission_id"]),),
        ).fetchall()
        network_row = conn.execute(
            """
            SELECT id, total_bandwidth, total_power, target_snr_db, node_count, base_station_count, channel_scenario,
                   is_active, created_by_user_id, created_at
            FROM network_config
            WHERE id = ?
            """,
            (int(run_record["network_config_id"]),),
        ).fetchone()
        slice_row = conn.execute(
            """
            SELECT id, slice_count, slice_names_json, codec_count, codec_modality,
                   knowledge_bases_json, is_active, created_by_user_id, created_at
            FROM slice_config
            WHERE id = ?
            """,
            (int(run_record["slice_config_id"]),),
        ).fetchone()
        adaptation_rows = conn.execute(
            """
            SELECT
                ar.task_item_id, ti.biz_user_code, ti.domain_type, ti.requirement_type,
                ar.matched_slice_id, ar.matched_slice_name, ar.codec_id, ar.kb_id, ar.similarity_score
            FROM adaptation_result ar
            JOIN task_item ti ON ti.id = ar.task_item_id
            WHERE ar.run_id = ?
            ORDER BY ar.task_item_id ASC
            """,
            (int(run_id),),
        ).fetchall()
        allocation_rows = conn.execute(
            """
            SELECT
                al.task_item_id, ti.biz_user_code, al.slice_id, al.bandwidth, al.power
            FROM allocation_result al
            JOIN task_item ti ON ti.id = al.task_item_id
            WHERE al.run_id = ?
            ORDER BY al.task_item_id ASC
            """,
            (int(run_id),),
        ).fetchall()
        performance_rows = conn.execute(
            """
            SELECT
                pr.task_item_id, ti.biz_user_code, ti.domain_type, ti.requirement_type,
                pr.slice_id, pr.fidelity, pr.delay_ms, pr.snr_db,
                pr.similarity_score, pr.knowledge_factor, pr.s_se, pr.pass,
                pr.source_text, pr.encoded_signal_shape, pr.encoded_signal_preview, pr.decoded_text, pr.token_match_rate,
                pr.sample_index, pr.task_pkl, pr.task_vocab,
                pr.model_profile, pr.checkpoint_name, pr.decode_error,
                al.bandwidth, al.power
            FROM performance_result pr
            JOIN task_item ti ON ti.id = pr.task_item_id
            LEFT JOIN allocation_result al
                ON al.run_id = pr.run_id AND al.task_item_id = pr.task_item_id
            WHERE pr.run_id = ?
            ORDER BY pr.task_item_id ASC
            """,
            (int(run_id),),
        ).fetchall()

    if submission_row is None or network_row is None or slice_row is None:
        return None

    task_row_dicts = [dict(row) for row in task_rows]
    business_output = _build_business_output_from_task_rows(task_row_dicts)

    network_config = network_model_from_record(dict(network_row))
    network_output = build_network_config(network_config)

    slice_request = slice_request_from_record(dict(slice_row))
    slicing_output = build_slice_config(slice_request)

    adaptation_output = AdaptationResponse(
        relations=[
            AdaptationRow(
                user_id=str(row["biz_user_code"]),
                domain_type=str(row["domain_type"]),
                requirement_type=str(row["requirement_type"]),
                matched_slice_id=str(row["matched_slice_id"]),
                matched_slice_name=str(row["matched_slice_name"]),
                codec_id=str(row["codec_id"]),
                kb_id=str(row["kb_id"]),
                similarity_score=float(row["similarity_score"]),
            )
            for row in adaptation_rows
        ]
    )

    allocation_items = [
        UserResourceAllocation(
            user_id=str(row["biz_user_code"]),
            slice_id=str(row["slice_id"]),
            bandwidth=float(row["bandwidth"]),
            power=float(row["power"]),
        )
        for row in allocation_rows
    ]
    used_resources, remaining_resources, timeline = _build_allocation_metrics(
        allocation_items,
        network_config,
        str(run_record.get("allocation_algorithm", "semslice")),
    )
    allocation_output = ResourceAllocationResponseV2(
        allocations=allocation_items,
        used_resources=used_resources,
        remaining_resources=remaining_resources,
        timeline=timeline,
    )

    user_metrics = []
    for row in performance_rows:
        fidelity = float(row["fidelity"])
        delay_ms = float(row["delay_ms"])
        user_metrics.append(
            {
                "user_id": str(row["biz_user_code"]),
                "slice_id": str(row["slice_id"]),
                "domain_type": str(row["domain_type"]),
                "requirement_type": str(row["requirement_type"]),
                "fidelity": fidelity,
                "delay_ms": delay_ms,
                "snr_db": float(row["snr_db"]),
                "bandwidth": float(row["bandwidth"] or 0.0),
                "power": float(row["power"] or 0.0),
                "similarity_score": float(row["similarity_score"]),
                "knowledge_factor": float(row["knowledge_factor"]),
                "s_se": float(row["s_se"] or 0.0),
                "pass": bool(row["pass"]),
                "source_text": str(row["source_text"] or ""),
                "encoded_signal_shape": str(row["encoded_signal_shape"] or ""),
                "encoded_signal_preview": str(row["encoded_signal_preview"] or ""),
                "decoded_text": str(row["decoded_text"] or ""),
                "token_match_rate": float(row["token_match_rate"] or fidelity),
                "sample_index": int(row["sample_index"] or 0),
                "task_pkl": str(row["task_pkl"] or ""),
                "task_vocab": str(row["task_vocab"] or ""),
                "model_profile": str(row["model_profile"] or ""),
                "checkpoint_name": str(row["checkpoint_name"] or ""),
                "decode_error": str(row["decode_error"] or ""),
            }
        )

    charts = {
        "fidelity_by_user": [{"label": row["user_id"], "value": float(row["fidelity"])} for row in user_metrics],
        "delay_by_user": [{"label": row["user_id"], "value": float(row["delay_ms"])} for row in user_metrics],
        "resource_by_user": [
            {
                "label": row["user_id"],
                "bandwidth": float(row["bandwidth"]),
                "power": float(row["power"]),
            }
            for row in user_metrics
        ],
    }
    performance_output = PerformanceEvaluateResponse(
        core_metrics={
            "avg_fidelity": round(float(run_record.get("avg_fidelity") or 0.0), 4),
            "avg_delay_ms": round(float(run_record.get("avg_delay_ms") or 0.0), 4),
            "avg_s_se": round(float(run_record.get("avg_s_se") or 0.0), 5),
        },
        user_metrics=user_metrics,
        charts=charts,
    )

    return FullSystemResponse(
        business_output=business_output,
        network_output=network_output,
        slicing_output=slicing_output,
        adaptation_output=adaptation_output,
        allocation_output=allocation_output,
        performance_output=performance_output,
    )


def get_strategy_runs_for_submission(submission_id: int) -> Dict[str, FullSystemResponse]:
    runs = _load_run_rows(submission_id)
    result: Dict[str, FullSystemResponse] = {}
    for row in runs:
        strategy = str(row["allocation_algorithm"])
        if strategy in result:
            continue
        response = build_full_system_response(int(row["id"]))
        if response is not None:
            result[strategy] = response
    return result


def get_latest_strategy_runs(owner_user_id: Optional[int] = None) -> Tuple[Optional[int], Dict[str, FullSystemResponse]]:
    submission_id = get_latest_submission_id(owner_user_id=owner_user_id)
    if submission_id is None:
        return None, {}
    return submission_id, get_strategy_runs_for_submission(submission_id)


def get_strategy_compare_summary(submission_id: int) -> List[Dict[str, object]]:
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT strategy, avg_delay_ms, avg_ss, avg_s_se, task_count, created_at
            FROM strategy_compare_summary
            WHERE submission_id = ?
            ORDER BY id ASC
            """,
            (int(submission_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_submission_task_items(submission_id: int) -> List[Dict[str, object]]:
    _, task_rows = _load_submission_rows(submission_id)
    return task_rows


def get_business_output_for_submission(submission_id: int) -> BusinessConfigResponse:
    return _build_business_output_from_task_rows(get_submission_task_items(submission_id))


def build_task_board(response: FullSystemResponse, allocation_algorithm: str) -> List[Dict[str, object]]:
    adapts = response.adaptation_output.relations
    allocs = {row.user_id: row for row in response.allocation_output.allocations}
    metrics = {str(row.get("user_id")): row for row in response.performance_output.user_metrics}
    business_users = {row.user_id: row for row in response.business_output.users}
    network = response.network_output.network

    rows: List[Dict[str, object]] = []
    for rel in adapts:
        alloc = allocs.get(rel.user_id)
        metric = metrics.get(rel.user_id, {})
        business_user = business_users.get(rel.user_id)
        rows.append(
            {
                "user_id": rel.user_id,
                "requirement": rel.requirement_type,
                "domain": rel.domain_type,
                "slice": rel.matched_slice_name,
                "slice_id": rel.matched_slice_id,
                "bandwidth": float(getattr(alloc, "bandwidth", 0.0)),
                "power": float(getattr(alloc, "power", 0.0)),
                "delay_ms": float(metric.get("delay_ms", 0.0)),
                "fidelity": float(metric.get("fidelity", 0.0)),
                "snr_db": float(metric.get("snr_db", 0.0)),
                "task_pkl": getattr(business_user, "task_pkl", None),
                "task_vocab": str(metric.get("task_vocab") or getattr(business_user, "task_vocab", None) or ""),
                "sample_index": getattr(business_user, "sample_index", 0),
                "source_text": str(metric.get("source_text", "")),
                "encoded_signal_shape": str(metric.get("encoded_signal_shape", "")),
                "encoded_signal_preview": str(metric.get("encoded_signal_preview", "")),
                "decoded_text": str(metric.get("decoded_text", "")),
                "token_match_rate": float(metric.get("token_match_rate", metric.get("fidelity", 0.0))),
                "s_se": float(metric.get("s_se", 0.0)),
                "model_profile": str(metric.get("model_profile", "")),
                "checkpoint_name": str(metric.get("checkpoint_name", "")),
                "decode_error": str(metric.get("decode_error", "")),
                "allocation_algorithm": str(allocation_algorithm),
                "updated_at": now_iso(),
                "total_bandwidth": float(network.get("total_bandwidth", 0.0)),
                "total_power": float(network.get("total_power", 0.0)),
                "target_snr_db": float(network.get("target_snr_db", 6.0)),
                "node_count": int(network.get("node_count", 5)),
                "base_station_count": int(network.get("base_station_count", 1)),
            }
        )
    return rows


def build_state_snapshot(current_strategy: str, owner_user_id: Optional[int]) -> Dict[str, object]:
    network_ready = get_active_network_record() is not None
    slicing_ready = get_active_slice_record() is not None
    submission_id, strategy_runs = get_latest_strategy_runs(owner_user_id=owner_user_id)
    strategy_boards = {
        strategy: build_task_board(response, strategy)
        for strategy, response in strategy_runs.items()
    }
    selected = current_strategy if current_strategy in strategy_runs else next(iter(strategy_runs.keys()), None)
    last_new_run = strategy_runs.get(selected) if selected else None
    compare_rows = get_strategy_compare_summary(submission_id) if submission_id is not None else []

    return {
        "network_configured": network_ready,
        "slicing_configured": slicing_ready,
        "admin_config_ready": network_ready and slicing_ready,
        "strategy_runs": strategy_runs,
        "strategy_boards": strategy_boards,
        "admin_task_board": strategy_boards.get(selected, []),
        "pending_tasks": [],
        "last_new_run": last_new_run,
        "allocation_algorithm": current_strategy,
        "compare_summary": compare_rows,
    }


def get_run_id_by_submission_and_strategy(submission_id: int, strategy: str) -> Optional[int]:
    with connection_scope() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM workflow_run
            WHERE submission_id = ? AND allocation_algorithm = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(submission_id), str(strategy)),
        ).fetchone()
    return int(row["id"]) if row else None
