from datetime import time
from pathlib import Path

import streamlit as st

# Step 1: bring the logic layer into the UI layer.
from pawpal_system import VALID_FREQUENCIES, Owner, Pet, Scheduler, Task

# PawPal AI: proposal pipeline on top of the original deterministic system.
from pawpal_ai.interaction_logger import InteractionLogger
from pawpal_ai.llm_client import LLMClientError, create_client_from_env
from pawpal_ai.retriever import KnowledgeRetriever
from pawpal_ai.schemas import TaskProposal
from pawpal_ai.workflow import PawPalAIWorkflow, apply_approved_tasks

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

with st.expander("Scenario"):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

The scheduling logic lives in `pawpal_system.py`; this app is the interactive UI on top of it.
"""
    )

# Step 2: Streamlit reruns this script top-to-bottom on every interaction, so a
# plain `owner = Owner(...)` here would be reborn (empty) on every click.
# st.session_state is the per-session "vault" that survives reruns — we create
# the Owner only if it isn't already stored there.
if "owner" not in st.session_state:
    st.session_state.owner = Owner("Jordan")
owner = st.session_state.owner

# ---------------- Owner ----------------
st.subheader("Owner")
owner_name = st.text_input("Owner name", value=owner.name)
if owner_name.strip() and owner_name != owner.name:
    owner.name = owner_name.strip()

# ---------------- Pets ----------------
st.subheader("Pets")

with st.form("add_pet_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        pet_name = st.text_input("Pet name", placeholder="Mochi")
    with col2:
        species = st.selectbox("Species", ["dog", "cat", "other"])
    # Step 3: the form submits to Owner.add_pet — the Owner class owns the pet list.
    if st.form_submit_button("Add pet"):
        name = pet_name.strip()
        if not name:
            st.error("Please enter a pet name.")
        elif any(p.name == name for p in owner.get_all_pets()):
            st.error(f"{name} is already one of {owner.name}'s pets.")
        else:
            owner.add_pet(Pet(name, species))

pets = owner.get_all_pets()
if pets:
    st.write(f"{owner.name}'s pets: " + ", ".join(f"{p.name} ({p.species})" for p in pets))
else:
    st.info("No pets yet. Add one above.")

# ---------------- Tasks ----------------
st.subheader("Tasks")

if pets:
    with st.form("add_task_form", clear_on_submit=True):
        target_pet_name = st.selectbox("For which pet?", [p.name for p in pets])
        description = st.text_input("Task description", placeholder="Morning walk")
        col1, col2 = st.columns(2)
        with col1:
            task_time = st.time_input("Time", value=time(8, 0))
            duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
        with col2:
            priority = st.selectbox("Priority", ["high", "medium", "low"])
            frequency = st.selectbox("Frequency", sorted(VALID_FREQUENCIES))
        # Step 3: the form submits to Pet.add_task — each pet owns its task list,
        # and add_task stamps the task with the pet's name.
        if st.form_submit_button("Add task"):
            if not description.strip():
                st.error("Please enter a task description.")
            else:
                try:
                    task = Task(
                        description=description.strip(),
                        pet_name="",  # set by add_task
                        time=task_time.strftime("%H:%M"),
                        duration_mins=int(duration),
                        priority=priority,
                        frequency=frequency,
                    )
                except ValueError as err:
                    st.error(str(err))
                else:
                    next(p for p in pets if p.name == target_pet_name).add_task(task)

    all_tasks = [t for p in pets for t in p.get_tasks()]
    if all_tasks:
        st.write("All tasks:")
        st.table(
            [
                {
                    "Pet": t.pet_name,
                    "Task": t.description,
                    "Time": t.time,
                    "Duration (min)": t.duration_mins,
                    "Priority": t.priority,
                    "Frequency": t.frequency,
                    "Due": str(t.due_date),
                    "Done": "✅" if t.is_complete else "—",
                }
                for t in all_tasks
            ]
        )
    else:
        st.info("No tasks yet. Add one above.")
else:
    st.caption("Add a pet first, then you can schedule tasks for it.")

st.divider()

# ---------------- PawPal AI Task Assistant ----------------
st.subheader("✨ PawPal AI Task Assistant")


@st.cache_resource
def get_ai_components():
    """Build the retriever + LLM client once per server process."""
    retriever = KnowledgeRetriever(Path(__file__).parent / "knowledge_base")
    try:
        client, mode = create_client_from_env()
    except LLMClientError as err:
        # Any live-provider setup error falls back to demo, so a typo in the
        # provider name or a missing key cannot take down the application.
        from pawpal_ai.demo_client import DemoLLMClient

        return retriever, DemoLLMClient(), "demo", str(err)
    return retriever, client, mode, None


def run_ai_workflow(request_text):
    retriever, client, mode, _ = get_ai_components()
    workflow = PawPalAIWorkflow(retriever, client, logger=InteractionLogger())
    return workflow.run(request_text, owner, Scheduler(owner))


if not pets:
    st.caption("Add a pet first, then describe care tasks in plain English.")
else:
    _, _, ai_mode, ai_mode_error = get_ai_components()
    if ai_mode == "live":
        st.caption("Mode: **live model**")
    else:
        st.caption("Mode: **demo** (deterministic offline extractor — no API key needed)")
        if ai_mode_error:
            st.info(f"Live mode unavailable: {ai_mode_error}")
    st.warning(
        "AI proposals are suggestions only. Review every task below — nothing "
        "is added to the schedule until you approve it.", icon="⚠️"
    )

    with st.form("ai_request_form"):
        st.selectbox(
            "Pet focus (optional — the request text decides)",
            ["All pets"] + [p.name for p in pets],
            key="ai_pet_focus",
        )
        ai_request = st.text_area(
            "Describe the care tasks in plain English",
            placeholder=(
                "Biscuit needs a 30-minute walk every morning around 8. "
                "Feed him after the walk. Clean Mochi's litter box every "
                "evening at 6."
            ),
            key="ai_request_text",
        )
        if st.form_submit_button("✨ Generate proposal"):
            st.session_state.ai_result = run_ai_workflow(ai_request)
            st.session_state.pop("ai_applied", None)

    ai_result = st.session_state.get("ai_result")
    if ai_result is not None:
        # ----- status banner
        if ai_result.status == "ready_for_review":
            st.success(ai_result.user_message)
        elif ai_result.status == "needs_user_information":
            st.warning(ai_result.user_message)
        elif ai_result.status in ("guardrail_rejected", "model_error"):
            st.error(ai_result.user_message)
        else:  # validation_failed
            st.warning(ai_result.user_message)

        # ----- workflow details: retrieved context, repair, trace
        if ai_result.retrieved_chunks:
            with st.expander(
                f"Retrieved context ({len(ai_result.retrieved_chunks)} sources)"
            ):
                for chunk in ai_result.retrieved_chunks:
                    st.markdown(f"**`{chunk.source_id}`** (score {chunk.score})")
                    st.caption(chunk.text[:400])
        if ai_result.repair_attempted:
            st.info("One automatic repair attempt was made on this proposal.")
        if ai_result.validation and ai_result.validation.issues:
            with st.expander(
                f"Validation issues ({len(ai_result.validation.issues)})"
            ):
                for issue in ai_result.validation.issues:
                    icon = "🛑" if issue.severity == "error" else "⚠️"
                    st.markdown(f"{icon} `{issue.code}` — {issue.message}")

        # ----- review & approve proposals
        proposal = ai_result.proposal
        if proposal and proposal.tasks and ai_result.validation:
            valid_tasks = set(map(id, ai_result.validation.valid_tasks))
            error_indexes = {
                issue.task_index for issue in ai_result.validation.issues
                if issue.severity == "error" and issue.task_index is not None
            }
            st.markdown("#### Review proposed tasks")
            with st.form("ai_review_form"):
                approvals = []
                for index, task in enumerate(proposal.tasks):
                    is_valid = id(task) in valid_tasks and index not in error_indexes
                    badge = "✅ valid" if is_valid else "🛑 invalid — fix before approving"
                    st.markdown(f"**Task {index + 1}: {task.description}** ({badge})")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        pet_name = st.selectbox(
                            "Pet", [p.name for p in pets],
                            index=[p.name for p in pets].index(task.pet_name)
                            if task.pet_name in [p.name for p in pets] else 0,
                            key=f"ai_pet_{index}",
                        )
                        description = st.text_input(
                            "Description", value=task.description,
                            key=f"ai_desc_{index}",
                        )
                    with col2:
                        time_value = st.text_input(
                            "Time (HH:MM)", value=task.time, key=f"ai_time_{index}"
                        )
                        duration = st.number_input(
                            "Duration (min)", min_value=1, max_value=240,
                            value=int(task.duration_mins)
                            if 1 <= task.duration_mins <= 240 else 15,
                            key=f"ai_dur_{index}",
                        )
                    with col3:
                        priority = st.selectbox(
                            "Priority", ["high", "medium", "low"],
                            index=["high", "medium", "low"].index(task.priority)
                            if task.priority in ("high", "medium", "low") else 1,
                            key=f"ai_prio_{index}",
                        )
                        frequency = st.selectbox(
                            "Frequency", sorted(VALID_FREQUENCIES),
                            index=sorted(VALID_FREQUENCIES).index(task.frequency)
                            if task.frequency in VALID_FREQUENCIES else 0,
                            key=f"ai_freq_{index}",
                        )
                    st.caption(
                        f"Why: {task.explanation}  \n"
                        f"Confidence: {task.confidence:.2f} · "
                        f"Sources: {', '.join(task.source_ids) or '(none)'}"
                    )
                    approved = st.checkbox(
                        "Approve this task", key=f"ai_approve_{index}",
                        value=False,
                    )
                    approvals.append((approved, pet_name, description, time_value,
                                      int(duration), priority, frequency, task))
                    st.divider()

                if st.form_submit_button("Add Approved Tasks"):
                    selected = []
                    for (approved, pet_name, description, time_value, duration,
                         priority, frequency, original) in approvals:
                        if not approved:
                            continue
                        try:
                            selected.append(TaskProposal(
                                pet_name=pet_name,
                                description=description,
                                time=time_value.strip(),
                                duration_mins=duration,
                                priority=priority,
                                frequency=frequency,
                                explanation=original.explanation,
                                confidence=original.confidence,
                                source_ids=original.source_ids,
                            ))
                        except Exception as err:
                            st.error(f"'{description}' could not be prepared: {err}")
                    if not selected:
                        st.warning("No tasks were approved — nothing was added.")
                    else:
                        added, review = apply_approved_tasks(
                            selected, owner, Scheduler(owner),
                            ai_result.retrieved_chunks,
                            logger=InteractionLogger(),
                        )
                        if added:
                            # Clear the pending proposal so a page refresh
                            # cannot re-add the same tasks.
                            st.session_state.pop("ai_result", None)
                            st.session_state.flash = (
                                f"Added {added} AI-proposed task(s) to the "
                                "schedule after your approval."
                            )
                            st.rerun()
                        else:
                            st.error(
                                "The approved tasks failed revalidation — "
                                "nothing was added. Issues: "
                                + "; ".join(i.message for i in review.issues
                                            if i.severity == "error")
                            )

st.divider()

# ---------------- Today's Schedule ----------------
st.subheader("Today's Schedule")

scheduler = Scheduler(owner)
schedule = scheduler.get_todays_schedule()  # incomplete tasks due today, time-sorted

# Flash message from the previous rerun (e.g., after completing a task).
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

if not pets or not schedule:
    st.info("Nothing on today's schedule yet — add some tasks above.")
else:
    # Filtering controls, wired to Scheduler.filter_by_pet
    pet_filter = st.selectbox("Show tasks for", ["All pets"] + [p.name for p in pets])
    if pet_filter != "All pets":
        schedule = scheduler.filter_by_pet(schedule, pet_filter)

    # Conflict warnings surface automatically — no extra click needed.
    warnings = scheduler.conflict_warnings(schedule)
    if warnings:
        for warning in warnings:
            st.warning(f"Schedule conflict: {warning}. Consider moving one of these tasks.")
    else:
        st.success("No scheduling conflicts — this plan is doable!")

    # One row per task with a "Done" button; completing a recurring task
    # spawns its next occurrence via Scheduler.mark_task_complete.
    for row, task in enumerate(schedule):
        time_col, desc_col, done_col = st.columns([2, 6, 2])
        time_col.markdown(f"**{task.time}**")
        desc_col.markdown(
            f"{task.description} — {task.pet_name} "
            f"({task.duration_mins} min, {task.priority} priority, {task.frequency})"
        )
        if done_col.button("Done ✅", key=f"done_{row}_{task.pet_name}_{task.description}"):
            next_task = scheduler.mark_task_complete(task)
            message = f"Completed '{task.description}' for {task.pet_name}."
            if next_task:
                message += f" Next occurrence scheduled for {next_task.due_date}."
            st.session_state.flash = message
            st.rerun()

    # Completed tasks, via Scheduler.filter_by_status
    completed = scheduler.filter_by_status(
        [t for p in pets for t in p.get_tasks()], is_complete=True
    )
    if completed:
        with st.expander(f"Completed tasks ({len(completed)})"):
            for task in completed:
                st.markdown(f"~~{task.time} {task.description} — {task.pet_name}~~")
