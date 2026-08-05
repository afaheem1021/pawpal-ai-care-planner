"""Visual-only Streamlit helpers for the PawPal AI dashboard.

These functions render escaped HTML and styles. They do not own application
state, create tasks, call models, or make scheduling decisions.
"""

from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from typing import Optional

import streamlit as st


def render_html(markup: str) -> None:
    """Render component HTML as one compact block so Markdown cannot recode it."""
    compact = " ".join(line.strip() for line in markup.splitlines() if line.strip())
    st.markdown(compact, unsafe_allow_html=True)


def load_styles(path: Path) -> None:
    """Load the local design system without an external network dependency."""
    css = path.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def pet_emoji(species: str) -> str:
    return {"dog": "🐶", "cat": "🐱"}.get(species, "🐾")


def pet_tone(species: str) -> str:
    return species if species in {"dog", "cat"} else "other"


def render_brand() -> None:
    render_html(
        """
        <div class="brand-lockup">
            <div class="brand-mark" aria-hidden="true">🐾</div>
            <div>
                <div class="brand-name">PawPal AI</div>
                <div class="brand-tagline">Care planning, made calmer.</div>
            </div>
        </div>
        """
    )


def render_pet_chip(pet, task_count: int) -> None:
    task_label = "task" if task_count == 1 else "tasks"
    render_html(
        f"""
        <div class="pet-chip">
            <div class="pet-avatar {pet_tone(pet.species)}" aria-hidden="true">
                {pet_emoji(pet.species)}
            </div>
            <div>
                <div class="pet-name">{escape(pet.name)}</div>
                <div class="pet-meta">{escape(pet.species)} · {task_count} {task_label}</div>
            </div>
        </div>
        """
    )


def render_workspace_header(owner_name: str, ai_mode: str) -> None:
    mode_text = "Gemini live" if ai_mode == "live" else "Offline demo"
    render_html(
        f"""
        <section class="workspace-header">
            <div>
                <div class="workspace-eyebrow">{date.today().strftime('%A · %B %d')}</div>
                <h1>Good day, {escape(owner_name or 'there')}.</h1>
                <p class="workspace-subtitle">Plan a calmer care routine, review AI
                suggestions, and keep every pet's day moving in one place.</p>
            </div>
            <div class="header-status" aria-label="AI assistant status">
                <div class="header-status-label">Assistant status</div>
                <div class="header-status-value">
                    <span class="live-dot" aria-hidden="true"></span>{mode_text}
                </div>
            </div>
        </section>
        """
    )


def render_summary_strip(pet_count: int, due_count: int, completed_count: int,
                         ai_mode: str) -> None:
    mode_text = "Gemini" if ai_mode == "live" else "Demo"
    items = [
        ("🐾", "Pets", str(pet_count)),
        ("🗓️", "Due today", str(due_count)),
        ("✓", "Completed", str(completed_count)),
        ("✨", "AI mode", mode_text),
    ]
    cards = "".join(
        f'<div class="summary-card">'
        f'<div class="summary-icon" aria-hidden="true">{icon}</div>'
        f'<div><div class="summary-label">{label}</div>'
        f'<div class="summary-value">{value}</div></div></div>'
        for icon, label, value in items
    )
    render_html(f'<div class="summary-strip">{cards}</div>')


def render_section_heading(kicker: str, title: str, copy: str = "",
                           mode: Optional[str] = None) -> None:
    copy_html = f'<div class="section-copy">{escape(copy)}</div>' if copy else ""
    mode_html = ""
    if mode:
        demo_class = " demo" if mode == "demo" else ""
        label = "Offline demo" if mode == "demo" else "Gemini live"
        mode_html = (
            f'<div class="mode-pill{demo_class}"><span class="mode-dot"></span>'
            f'{label}</div>'
        )
    render_html(
        f"""
        <div class="section-heading">
            <div class="section-kicker">{escape(kicker)}</div>
            <div class="section-title-row">
                <div class="section-title">{escape(title)}</div>
                {mode_html}
            </div>
            {copy_html}
        </div>
        """
    )


def render_empty_state(icon: str, title: str, copy: str) -> None:
    render_html(
        f"""
        <div class="empty-state">
            <div class="empty-icon" aria-hidden="true">{icon}</div>
            <div class="empty-title">{escape(title)}</div>
            <div class="empty-copy">{escape(copy)}</div>
        </div>
        """
    )


def render_review_progress() -> None:
    render_html(
        """
        <div class="review-progress" aria-label="AI proposal progress">
            <div class="review-step">1 · Request understood</div>
            <div class="review-step active">2 · Review proposals</div>
            <div class="review-step">3 · Add approved tasks</div>
        </div>
        """
    )


def render_proposal_header(index: int, task, is_valid: bool, species: str) -> None:
    status_class = "" if is_valid else " invalid"
    status = "Ready to approve" if is_valid else "Needs a fix"
    confidence = max(0, min(100, round(task.confidence * 100)))
    render_html(
        f"""
        <div class="proposal-marker"></div>
        <div class="proposal-head">
            <div class="proposal-identity">
                <div class="proposal-number">{index + 1}</div>
                <div>
                    <div class="proposal-title">{escape(task.description)}</div>
                    <div class="proposal-pet">{pet_emoji(species)} {escape(task.pet_name)} ·
                    {confidence}% confidence</div>
                </div>
            </div>
            <div class="status-badge{status_class}">{status}</div>
        </div>
        <div class="confidence-track" aria-label="Confidence {confidence}%">
            <div class="confidence-fill" style="width:{confidence}%"></div>
        </div>
        """
    )


def render_schedule_task(task, species: str) -> None:
    render_html(
        f"""
        <div class="timeline-marker"></div>
        <div class="timeline-card-head">
            <div class="task-time">{escape(task.time)}</div>
            <div class="task-details">
                <div class="task-title">{escape(task.description)}</div>
                <div class="task-meta">{pet_emoji(species)} {escape(task.pet_name)} ·
                {task.duration_mins} minutes</div>
                <span class="mini-badge {escape(task.priority)}">{escape(task.priority)}</span>
                <span class="mini-badge">{escape(task.frequency)}</span>
            </div>
        </div>
        """
    )


def render_footer() -> None:
    render_html(
        """
        <p class="tiny-note" style="text-align:center; margin-top:2.3rem;">
            PawPal AI proposes. You decide. The deterministic scheduler remains
            the source of truth for every task.
        </p>
        """
    )
