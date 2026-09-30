"""Streamlit UI for durable Selenium scraping jobs and saved market evidence."""

from __future__ import annotations

import math

import streamlit as st

from src.config import SUPPORTED_DOMAINS, get_settings
from src.db import DatabaseError, SQLiteRepository
from src.jobs import enqueue_analysis, enqueue_competitors, enqueue_scrape
from src.llm import analysis_markdown
from src.models import JobStatus, ValidationError
from src.services import create_tracked_context

PAGE_SIZE = 10


def render_header() -> None:
    st.title("Amazon Competitor Analysis")
    st.caption("Collect product evidence with Selenium, then compare saved competitor snapshots.")


def enqueue_product(repo: SQLiteRepository) -> None:
    with st.form("product-input"):
        asin = st.text_input("ASIN", placeholder="e.g., B0CX23VSAS")
        location = st.text_input("Zip/Postal Code", placeholder="e.g., 83980")
        domain = st.selectbox("Domain", SUPPORTED_DOMAINS)
        submitted = st.form_submit_button("Scrape product")
    if not submitted:
        return
    try:
        context = create_tracked_context(repo, asin, domain, location)
        job = enqueue_scrape(repo, context.id)
    except (ValidationError, DatabaseError) as exc:
        st.error(str(exc))
        return
    st.session_state["selected_context_id"] = context.id
    st.session_state["last_job_id"] = job.id
    st.info(f"Product scrape queued: {job.id}")


def render_snapshot(snapshot: dict[str, object] | None) -> None:
    if not snapshot:
        st.caption("No completed product snapshot yet.")
        return
    columns = st.columns([1, 2])
    images = snapshot.get("images")
    if isinstance(images, list) and images:
        columns[0].image(images[0], width=200)
    else:
        columns[0].caption("No image captured.")
    with columns[1]:
        st.subheader(str(snapshot.get("title") or snapshot.get("asin")))
        price = snapshot.get("price_text") or "Unavailable"
        currency = snapshot.get("currency") or "Unknown currency"
        metric, brand, availability = st.columns(3)
        metric.metric("Price", f"{price} ({currency})")
        brand.write(f"Brand: {snapshot.get('brand') or 'Unknown'}")
        availability.write(f"Availability: {snapshot.get('availability') or 'Unknown'}")
        st.caption(
            f"amazon.{snapshot.get('amazon_domain')} · Location: {snapshot.get('location_status')} · "
            f"Captured: {snapshot.get('captured_at')}"
        )
        if snapshot.get("canonical_url"):
            st.link_button("Open source page", str(snapshot["canonical_url"]))


def render_tracked_products(repo: SQLiteRepository) -> None:
    contexts, total = repo.list_tracked_contexts(PAGE_SIZE, 0)
    if not total:
        return
    st.divider()
    st.subheader("Tracked products")
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = int(st.number_input("Page", min_value=1, max_value=pages, value=1, key="tracked-page"))
    contexts, _ = repo.list_tracked_contexts(PAGE_SIZE, (page - 1) * PAGE_SIZE)
    st.caption(
        f"Showing {(page - 1) * PAGE_SIZE + 1}–{min(page * PAGE_SIZE, total)} of {total} tracked products"
    )
    for context in contexts:
        with st.container(border=True):
            render_snapshot(repo.get_latest_snapshot(context.id))
            if st.button("Select", key=f"select-context-{context.id}"):
                st.session_state["selected_context_id"] = context.id


def render_selected_context(repo: SQLiteRepository) -> None:
    context_id = st.session_state.get("selected_context_id")
    if not context_id:
        return
    context = repo.get_context(int(context_id))
    if not context:
        st.session_state.pop("selected_context_id", None)
        return
    snapshot = repo.get_latest_snapshot(context.id)
    run_id = repo.get_active_run_id(context.id)
    st.divider()
    st.subheader(f"Competitor analysis: {context.key.asin} on amazon.{context.key.domain}")
    render_snapshot(snapshot)
    left, right = st.columns(2)
    with left:
        if st.button(
            "Refresh competitors",
            key=f"refresh-{context.id}",
            disabled=snapshot is None,
        ):
            try:
                job = enqueue_competitors(repo, context.id)
                st.session_state["last_job_id"] = job.id
                st.info(f"Competitor job queued: {job.id}")
            except DatabaseError as exc:
                st.error(str(exc))
    with right:
        if st.button(
            "Analyze with LLM",
            type="primary",
            key=f"analyze-{context.id}",
            disabled=run_id is None,
        ):
            try:
                job = enqueue_analysis(repo, context.id)
                st.session_state["last_job_id"] = job.id
                st.info(f"Analysis job queued: {job.id}")
            except DatabaseError as exc:
                st.error(str(exc))
    if run_id:
        rows = repo.get_competitor_rows(run_id)
        st.caption(f"Current completed competitor run: {run_id} ({len(rows)} products)")
        for row in rows:
            sponsored = " · sponsored" if row["sponsored"] else ""
            st.write(
                f"{row['rank']}. {row['title'] or row['asin']} — {row['price_text'] or 'Unavailable'}{sponsored}"
            )
    else:
        st.caption(
            "No complete competitor run yet. A failed or partial refresh never replaces the previous complete run."
        )
    analysis = repo.latest_analysis(context.id)
    if analysis and analysis.get("output"):
        st.divider()
        st.markdown(
            analysis_markdown(analysis["output"], repo.get_competitor_rows(run_id))
            if run_id
            else ""
        )


JOB_POLL_SECONDS = get_settings().job_poll_seconds


@st.fragment(run_every=JOB_POLL_SECONDS if JOB_POLL_SECONDS > 0 else None)
def render_last_job(repo: SQLiteRepository) -> None:
    job_id = st.session_state.get("last_job_id")
    if not job_id:
        return
    job = repo.get_job(job_id)
    if not job:
        return
    status = f"Job {job.id}: {job.status.value} ({job.progress}%)"
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        st.progress(job.progress, text=status)
        return
    if job.error_message:
        st.warning(f"{status} — {job.error_message}")
    elif job.status == JobStatus.SUCCEEDED:
        st.success(status)
    else:
        st.info(status)
    refresh_key = f"terminal-job-refreshed-{job.id}"
    if not st.session_state.get(refresh_key):
        st.session_state[refresh_key] = True
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Amazon Competitor Analysis", page_icon="📚", layout="wide")
    render_header()
    try:
        repo = SQLiteRepository()
        repo.migrate()
        enqueue_product(repo)
        render_last_job(repo)
        render_tracked_products(repo)
        render_selected_context(repo)
    except DatabaseError as exc:
        st.error(f"Database is not ready: {exc}")


if __name__ == "__main__":
    main()
