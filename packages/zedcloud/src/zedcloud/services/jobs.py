"""Job service with completion waiters for asynchronous (bulk) operations."""

from __future__ import annotations

from zedcloud._generated.models import JobConfig, JobStatus, ZsrvResponse
from zedcloud._generated.services.jobs import AsyncJobsService as _AsyncJobsService
from zedcloud._generated.services.jobs import JobsService as _JobsService
from zedcloud.waiters import async_wait_until, state_in, wait_until

JOB_DONE = (JobStatus.JOB_STATUS_COMPLETED,)
JOB_FAILED = (JobStatus.JOB_STATUS_FAILED, JobStatus.JOB_STATUS_ABORTED)


def _job_id(job: str | ZsrvResponse) -> str:
    if isinstance(job, ZsrvResponse):
        if not job.job_id:
            raise ValueError("this response did not start a job (no job_id)")
        return job.job_id
    return job


class JobsService(_JobsService):
    """Bulk jobs."""

    def wait_for_job(
        self, job: str | ZsrvResponse, *, timeout: float = 1800.0, interval: float = 10.0
    ) -> JobConfig:
        """Wait for a job (by ID, or the ``ZsrvResponse`` that started it) to complete.

        Raises :class:`~zedcloud.errors.WaitFailedError` if the job fails or is aborted.
        """
        job_id = _job_id(job)
        return wait_until(
            lambda: self.get_job_by_id(job_id),
            state_in("status", JOB_DONE),
            failed=state_in("status", JOB_FAILED),
            timeout=timeout,
            interval=interval,
            description=f"job {job_id} to complete",
        )


class AsyncJobsService(_AsyncJobsService):
    """Bulk jobs (async)."""

    async def wait_for_job(
        self, job: str | ZsrvResponse, *, timeout: float = 1800.0, interval: float = 10.0
    ) -> JobConfig:
        """Wait for a job (by ID, or the ``ZsrvResponse`` that started it) to complete."""
        job_id = _job_id(job)
        return await async_wait_until(
            lambda: self.get_job_by_id(job_id),
            state_in("status", JOB_DONE),
            failed=state_in("status", JOB_FAILED),
            timeout=timeout,
            interval=interval,
            description=f"job {job_id} to complete",
        )
