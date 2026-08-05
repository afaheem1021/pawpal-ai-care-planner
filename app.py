from datetime import time
from html import escape
from pathlib import Path

import streamlit as st

from pawpal_ai.interaction_logger import InteractionLogger
from pawpal_ai.llm_client import LLMClientError, create_client_from_env
from pawpal_ai.retriever import KnowledgeRetriever
from pawpal_ai.schemas import TaskProposal
from pawpal_ai.workflow import PawPalAIWorkflow, apply_approved_tasks
from pawpal_system import VALID_FREQUENCIES, Owner, Pet, Scheduler, Task
from pawpal_ui import (
    load_styles,
    pet_emoji,
    render_brand,
    render_empty_state,
    render_footer,
    render_html,
    render_pet_chip,
    render_proposal_header,
    render_review_progress,
    render_schedule_task,
    render_section_heading,
    render_summary_strip,
    render_workspace_header,
)


ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="PawPal AI",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="auto",
)
load_styles(ROOT / "assets" / "styles.css")


# ---------------------------------------------------------------- AI services

@st.cache_resource
def get_ai_components():
    """Build the retriever and configured model client once per server."""
    retriever = KnowledgeRetriever(ROOT / "knowledge_base")
    try:
        client, mode = create_client_from_env()
    except LLMClientError as err:
        from pawpal_ai.demo_client import DemoLLMClient

        return retriever, DemoLLMClient(), "demo", str(err)
    return retriever, client, mode, None


def run_ai_workflow(request_text, owner):
    retriever, client, _, _ = get_ai_components()
    workflow = PawPalAIWorkflow(retriever, client, logger=InteractionLogger())
    return workflow.run(request_text, owner, Scheduler(owner))


# ------------------------------------------------------------ sidebar profile

def render_sidebar(owner):
    """Render owner and pet management without changing their data model."""
    with st.sidebar:
        render_brand()
        st.markdown('<div class="sidebar-label">Your household</div>',
                    unsafe_allow_html=True)

        owner_name = st.text_input("Owner name", value=owner.name)
        if owner_name.strip() and owner_name != owner.name:
            owner.name = owner_name.strip()

        with st.form("add_pet_form", clear_on_submit=True):
            pet_name = st.text_input("Pet name", placeholder="Mochi")
            species = st.selectbox("Species", ["dog", "cat", "other"])
            if st.form_submit_button("＋ Add pet", width="stretch"):
                name = pet_name.strip()
                if not name:
                    st.error("Please enter a pet name.")
                elif any(pet.name == name for pet in owner.get_all_pets()):
                    st.error(f"{name} is already one of {owner.name}'s pets.")
                else:
                    owner.add_pet(Pet(name, species))

        pets = owner.get_all_pets()
        if pets:
            st.markdown('<div class="sidebar-label">Pet roster</div>',
                        unsafe_allow_html=True)
            for pet in pets:
                render_pet_chip(pet, len(pet.get_tasks()))
        else:
            st.caption("Add your first pet to unlock planning tools.")

        st.divider()
        with st.expander("About PawPal"):
            st.markdown(
                "PawPal combines a deterministic scheduler with an AI proposal "
                "assistant. AI tasks are never added until you review and approve them."
            )


# --------------------------------------------------------------- AI workspace

def render_prompt_guide():
    """Keep prompt education available without adding visual weight."""
    with st.expander("💡 How to get the best care plan"):
        render_html(
            """
            <div class="prompt-guide-intro">
                Include the pet name, care action, start time, and repeat schedule.
                Duration is optional—PawPal can use an editable template default.
            </div>
            <div class="prompt-example">
                <strong>Multiple tasks</strong><br>
                Walk Ron at 8 AM. Walk Kitty at noon. Clean Ron at 10 AM.
                Clean Kitty at 12:45 PM.
            </div>
            <div class="prompt-example">
                <strong>Recurring and ordered tasks</strong><br>
                Walk Ron every morning at 8 for 30 minutes, then feed him immediately
                afterward. Clean Kitty every evening at 6.
            </div>
            <div class="prompt-guide-intro">
                Times outside your usual availability are kept exactly as requested
                and flagged for review.
            </div>
            """
        )


def render_ai_result_status(ai_result):
    if ai_result.status == "ready_for_review":
        st.success(ai_result.user_message)
    elif ai_result.status == "needs_user_information":
        st.warning(ai_result.user_message)
    elif ai_result.status in ("guardrail_rejected", "model_error"):
        st.error(ai_result.user_message)
    else:
        st.warning(ai_result.user_message)


def render_ai_diagnostics(ai_result):
    """Keep technical evidence accessible but visually secondary."""
    if ai_result.repair_attempted:
        st.info("One automatic repair attempt was made on this proposal.")

    issue_count = (
        len(ai_result.validation.issues)
        if ai_result.validation and ai_result.validation.issues
        else 0
    )
    detail_columns = st.columns(3)

    if ai_result.retrieved_chunks:
        with detail_columns[0].expander(
            f"Context · {len(ai_result.retrieved_chunks)}"
        ):
            for chunk in ai_result.retrieved_chunks:
                st.markdown(f"**`{chunk.source_id}`** · {chunk.score}")
                st.caption(chunk.text[:320])
    else:
        detail_columns[0].caption("No retrieved context")

    if issue_count:
        with detail_columns[1].expander(f"Validation · {issue_count}"):
            for issue in ai_result.validation.issues:
                icon = "🛑" if issue.severity == "error" else "⚠️"
                st.markdown(f"{icon} `{issue.code}` — {issue.message}")
    else:
        detail_columns[1].caption("Validation passed ✓")

    if ai_result.trace:
        with detail_columns[2].expander("Workflow trace"):
            for event in ai_result.trace:
                icon = "✅" if event.status in ("ok", "passed") else "⚠️"
                st.markdown(f"{icon} **{event.step}** — {event.summary}")


def build_selected_proposals(approvals):
    selected = []
    for (
        approved,
        pet_name,
        description,
        time_value,
        duration,
        priority,
        frequency,
        original,
    ) in approvals:
        if not approved:
            continue
        try:
            selected.append(
                TaskProposal(
                    pet_name=pet_name,
                    description=description,
                    time=time_value.strip(),
                    duration_mins=duration,
                    priority=priority,
                    frequency=frequency,
                    explanation=original.explanation,
                    confidence=original.confidence,
                    source_ids=original.source_ids,
                )
            )
        except Exception as err:
            st.error(f"'{description}' could not be prepared: {err}")
    return selected


def render_proposal_review(ai_result, owner, pets):
    proposal = ai_result.proposal
    if not proposal or not proposal.tasks or not ai_result.validation:
        return

    valid_tasks = set(map(id, ai_result.validation.valid_tasks))
    error_indexes = {
        issue.task_index
        for issue in ai_result.validation.issues
        if issue.severity == "error" and issue.task_index is not None
    }
    pet_names = [pet.name for pet in pets]
    species_by_name = {pet.name: pet.species for pet in pets}

    st.markdown("#### Review proposed tasks")
    st.caption("Edit anything that needs adjustment, then approve only what you want.")
    render_review_progress()

    with st.form("ai_review_form"):
        st.markdown('<div class="review-form-marker"></div>',
                    unsafe_allow_html=True)
        approvals = []

        for index, task in enumerate(proposal.tasks):
            is_valid = id(task) in valid_tasks and index not in error_indexes
            species = species_by_name.get(task.pet_name, "other")

            with st.container(border=True):
                render_proposal_header(index, task, is_valid, species)

                identity_col, description_col = st.columns([1, 2])
                with identity_col:
                    pet_name = st.selectbox(
                        "Pet",
                        pet_names,
                        index=pet_names.index(task.pet_name)
                        if task.pet_name in pet_names else 0,
                        key=f"ai_pet_{index}",
                    )
                with description_col:
                    description = st.text_input(
                        "Description", value=task.description,
                        key=f"ai_desc_{index}",
                    )

                time_col, duration_col, priority_col, frequency_col = st.columns(4)
                with time_col:
                    time_value = st.text_input(
                        "Time (HH:MM)", value=task.time,
                        key=f"ai_time_{index}",
                    )
                with duration_col:
                    duration = st.number_input(
                        "Duration (min)", min_value=1, max_value=240,
                        value=int(task.duration_mins)
                        if 1 <= task.duration_mins <= 240 else 15,
                        key=f"ai_dur_{index}",
                    )
                with priority_col:
                    priority = st.selectbox(
                        "Priority", ["high", "medium", "low"],
                        index=["high", "medium", "low"].index(task.priority)
                        if task.priority in ("high", "medium", "low") else 1,
                        key=f"ai_prio_{index}",
                    )
                with frequency_col:
                    frequency = st.selectbox(
                        "Frequency", sorted(VALID_FREQUENCIES),
                        index=sorted(VALID_FREQUENCIES).index(task.frequency)
                        if task.frequency in VALID_FREQUENCIES else 0,
                        key=f"ai_freq_{index}",
                    )

                with st.expander("Why this task and its sources"):
                    st.markdown(f"**Why:** {escape(task.explanation)}")
                    st.caption(
                        f"Confidence: {task.confidence:.2f} · "
                        f"Sources: {', '.join(task.source_ids) or '(none)'}"
                    )

                approved = st.checkbox(
                    "Approve this task", key=f"ai_approve_{index}", value=False
                )
                approvals.append(
                    (
                        approved,
                        pet_name,
                        description,
                        time_value,
                        int(duration),
                        priority,
                        frequency,
                        task,
                    )
                )

        if st.form_submit_button(
            "Add Approved Tasks to Schedule", type="primary", width="stretch"
        ):
            selected = build_selected_proposals(approvals)
            if not selected:
                st.warning("No tasks were approved — nothing was added.")
                return

            added, review = apply_approved_tasks(
                selected,
                owner,
                Scheduler(owner),
                ai_result.retrieved_chunks,
                logger=InteractionLogger(),
            )
            if added:
                st.session_state.pop("ai_result", None)
                st.session_state.flash = (
                    f"Added {added} AI-proposed task(s) to your schedule after approval."
                )
                st.rerun()

            st.error(
                "The approved tasks failed revalidation — nothing was added. Issues: "
                + "; ".join(
                    issue.message
                    for issue in review.issues
                    if issue.severity == "error"
                )
            )


def render_ai_panel(owner, pets, ai_mode, ai_mode_error):
    with st.container(border=True):
        st.markdown('<div class="panel-marker ai-panel-marker"></div>',
                    unsafe_allow_html=True)
        render_section_heading(
            "AI care planner",
            "Describe it naturally",
            "One request can create up to five editable task proposals.",
            mode=ai_mode,
        )

        if ai_mode == "demo" and ai_mode_error:
            st.info(f"Live mode unavailable: {ai_mode_error}")

        if not pets:
            render_empty_state(
                "👈",
                "Add a pet to begin",
                "Use the household sidebar first, then ask PawPal to build a care plan.",
            )
            return

        st.warning(
            "AI proposals are suggestions only. Nothing reaches the schedule "
            "until you review and approve it.",
            icon="🛡️",
        )
        render_prompt_guide()

        with st.form("ai_request_form"):
            st.selectbox(
                "Pet focus (optional — the request text decides)",
                ["All pets"] + [pet.name for pet in pets],
                key="ai_pet_focus",
            )
            ai_request = st.text_area(
                "Describe the care tasks in plain English",
                placeholder=(
                    "Walk Ron at 8 AM. Walk Kitty at noon. Clean Ron at 10 AM. "
                    "Clean Kitty at 12:45 PM."
                ),
                height=132,
                key="ai_request_text",
            )
            submitted = st.form_submit_button(
                "✨ Generate care plan", type="primary", width="stretch"
            )

        if submitted:
            st.session_state.pop("ai_generation_error", None)
            progress_message = (
                "Gemini is generating and validating your care plan…"
                if ai_mode == "live"
                else "PawPal AI is generating and validating your care plan…"
            )
            with st.spinner(progress_message):
                try:
                    st.session_state.ai_result = run_ai_workflow(ai_request, owner)
                except Exception as err:
                    st.session_state.pop("ai_result", None)
                    st.session_state.ai_generation_error = str(err)
                else:
                    st.session_state.pop("ai_applied", None)

        generation_error = st.session_state.get("ai_generation_error")
        if generation_error:
            st.error(
                "Proposal generation failed before PawPal could produce a result. "
                f"Details: {generation_error}"
            )

        ai_result = st.session_state.get("ai_result")
        if ai_result is not None:
            render_ai_result_status(ai_result)
            render_ai_diagnostics(ai_result)
            render_proposal_review(ai_result, owner, pets)


# ------------------------------------------------------------ daily timeline

def render_schedule_panel(owner, pets, scheduler, schedule, completed_tasks):
    with st.container(border=True):
        st.markdown('<div class="panel-marker schedule-panel-marker"></div>',
                    unsafe_allow_html=True)
        render_section_heading(
            "Today's rhythm",
            "Your care timeline",
            "Time-sorted, conflict-aware, and ready to check off.",
        )

        if not pets:
            render_empty_state(
                "🐾", "No household yet", "Your daily timeline appears after you add a pet."
            )
            return

        if not schedule:
            render_empty_state(
                "☀️",
                "A clear day",
                "Nothing is due today. Add a task manually or ask the AI planner.",
            )
        else:
            pet_filter = st.selectbox(
                "Show tasks for",
                ["All pets"] + [pet.name for pet in pets],
                key="today_pet_filter",
            )
            visible_schedule = schedule
            if pet_filter != "All pets":
                visible_schedule = scheduler.filter_by_pet(schedule, pet_filter)

            warnings = scheduler.conflict_warnings(visible_schedule)
            if warnings:
                for warning in warnings:
                    st.warning(f"Schedule conflict: {warning}", icon="⚠️")
            else:
                st.success("No schedule conflicts — today's plan is clear.", icon="✅")

            species_by_name = {pet.name: pet.species for pet in pets}
            for row, task in enumerate(visible_schedule):
                with st.container(border=True):
                    render_schedule_task(
                        task, species_by_name.get(task.pet_name, "other")
                    )
                    if st.button(
                        "Done ✓",
                        key=f"done_{row}_{task.pet_name}_{task.description}",
                        width="stretch",
                    ):
                        next_task = scheduler.mark_task_complete(task)
                        message = f"Completed '{task.description}' for {task.pet_name}."
                        if next_task:
                            message += (
                                f" Next occurrence scheduled for {next_task.due_date}."
                            )
                        st.session_state.flash = message
                        st.rerun()

        if completed_tasks:
            with st.expander(f"Completed care ({len(completed_tasks)})"):
                for task in completed_tasks:
                    st.markdown(
                        f"~~{escape(task.time)} · {escape(task.description)} "
                        f"— {escape(task.pet_name)}~~"
                    )


# ------------------------------------------------------------- care library

def render_manual_task_form(owner, pets):
    st.markdown("### Add a task manually")
    st.caption("Use structured entry when you already know the exact details.")
    if not pets:
        render_empty_state(
            "＋", "Add a pet first", "Manual scheduling unlocks after pet onboarding."
        )
        return

    with st.form("add_task_form", clear_on_submit=True):
        target_pet_name = st.selectbox(
            "For which pet?", [pet.name for pet in pets]
        )
        description = st.text_input("Task description", placeholder="Morning walk")
        time_col, duration_col = st.columns(2)
        with time_col:
            task_time = st.time_input("Time", value=time(8, 0))
        with duration_col:
            duration = st.number_input(
                "Duration (minutes)", min_value=1, max_value=240, value=20
            )
        priority_col, frequency_col = st.columns(2)
        with priority_col:
            priority = st.selectbox("Priority", ["high", "medium", "low"])
        with frequency_col:
            frequency = st.selectbox("Frequency", sorted(VALID_FREQUENCIES))

        if st.form_submit_button("＋ Add task to schedule", width="stretch"):
            if not description.strip():
                st.error("Please enter a task description.")
                return
            try:
                task = Task(
                    description=description.strip(),
                    pet_name="",
                    time=task_time.strftime("%H:%M"),
                    duration_mins=int(duration),
                    priority=priority,
                    frequency=frequency,
                )
            except ValueError as err:
                st.error(str(err))
                return

            next(pet for pet in pets if pet.name == target_pet_name).add_task(task)
            st.session_state.flash = f"Added '{task.description}' for {target_pet_name}."
            st.rerun()


def render_task_library(all_tasks):
    st.markdown("### Complete care library")
    st.caption("Every open and completed task, in one searchable view.")
    if not all_tasks:
        render_empty_state(
            "📋", "Your library is empty", "Create a task to start building the routine."
        )
        return

    st.dataframe(
        [
            {
                "Pet": task.pet_name,
                "Task": task.description,
                "Time": task.time,
                "Minutes": task.duration_mins,
                "Priority": task.priority.title(),
                "Repeats": task.frequency.title(),
                "Due": str(task.due_date),
                "Status": "Complete" if task.is_complete else "Open",
            }
            for task in all_tasks
        ],
        hide_index=True,
        width="stretch",
    )


def render_care_library(owner, pets, all_tasks):
    st.write("")
    render_section_heading(
        "Care library",
        "Build and browse the full routine",
        "Structured entry and a searchable view of every care task.",
    )
    manual_column, library_column = st.columns([.82, 1.18], gap="large")
    with manual_column:
        with st.container(border=True):
            st.markdown('<div class="library-marker"></div>',
                        unsafe_allow_html=True)
            render_manual_task_form(owner, pets)
    with library_column:
        with st.container(border=True):
            st.markdown('<div class="library-marker"></div>',
                        unsafe_allow_html=True)
            render_task_library(all_tasks)


# ----------------------------------------------------------------------- main

def main():
    if "owner" not in st.session_state:
        st.session_state.owner = Owner("Jordan")
    owner = st.session_state.owner

    render_sidebar(owner)

    pets = owner.get_all_pets()
    all_tasks = [task for pet in pets for task in pet.get_tasks()]
    scheduler = Scheduler(owner)
    schedule = scheduler.get_todays_schedule()
    completed_tasks = scheduler.filter_by_status(all_tasks, is_complete=True)
    _, _, ai_mode, ai_mode_error = get_ai_components()

    render_workspace_header(owner.name, ai_mode)
    render_summary_strip(
        len(pets), len(schedule), len(completed_tasks), ai_mode
    )

    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"), icon="✅")

    ai_column, schedule_column = st.columns([1.18, .82], gap="large")
    with ai_column:
        render_ai_panel(owner, pets, ai_mode, ai_mode_error)
    with schedule_column:
        render_schedule_panel(
            owner, pets, scheduler, schedule, completed_tasks
        )

    render_care_library(owner, pets, all_tasks)
    render_footer()


main()
