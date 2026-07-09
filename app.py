from datetime import time

import streamlit as st

# Step 1: bring the logic layer into the UI layer.
from pawpal_system import VALID_FREQUENCIES, Owner, Pet, Scheduler, Task

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
