"""Job-related MCP tools."""

from __future__ import annotations

from zedcloud_mcp.tools.base import ClientFactory, DumpFn, Handler, ToolSpec


def _list_jobs(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def list_jobs(
        name_pattern: str | None = None,
        project_name: str | None = None,
        page_size: float = 25,
    ) -> str:
        """List asynchronous bulk jobs."""
        result = get_client().jobs.query_jobs(
            name_pattern=name_pattern,
            project_name=project_name,
            next_page_size=page_size,
            summary=True,
        )
        return dump(result)

    return list_jobs


def _get_job(get_client: ClientFactory, dump: DumpFn) -> Handler:
    def get_job(job_id: str) -> str:
        """Get a job by ID."""
        return dump(get_client().jobs.get_job_by_id(job_id))

    return get_job


JOB_TOOLS = [
    ToolSpec(
        name="zedcloud_list_jobs",
        description="List asynchronous Zedcloud jobs.",
        make_handler=_list_jobs,
    ),
    ToolSpec(
        name="zedcloud_get_job",
        description="Get a Zedcloud job by ID.",
        make_handler=_get_job,
    ),
]
