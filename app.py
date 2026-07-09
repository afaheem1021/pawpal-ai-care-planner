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
        st.write("Current tasks:")
        st.table(
            [
                {
                    "Pet": t.pet_name,
                    "Task": t.description,
                    "Time": t.time,
                    "Duration (min)": t.duration_mins,
                    "Priority": t.priority,
                    "Frequency": t.frequency,
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

# ---------------- Schedule ----------------
st.subheader("Build Schedule")

if st.button("Generate schedule"):
    # Step 3: the button calls the Scheduler, which pulls tasks from the
    # Owner's pets (Scheduler -> Owner -> Pet -> Task) and sorts them by time.
    scheduler = Scheduler(owner)
    schedule = scheduler.get_todays_schedule()

    if not schedule:
        st.info("Nothing to schedule yet — add some tasks first.")
    else:
        st.markdown(f"#### Today's schedule for {owner.name}'s pets")
        st.table(
            [
                {
                    "Time": t.time,
                    "Pet": t.pet_name,
                    "Task": t.description,
                    "Duration (min)": t.duration_mins,
                    "Priority": t.priority,
                }
                for t in schedule
            ]
        )

        conflicts = scheduler.check_conflicts(schedule)
        if conflicts:
            st.warning("Scheduling conflicts detected:")
            for first, second in conflicts:
                st.markdown(
                    f"- **{first.description}** ({first.pet_name}, {first.time}, "
                    f"{first.duration_mins} min) overlaps **{second.description}** "
                    f"({second.pet_name}, {second.time})"
                )
        else:
            st.success("No scheduling conflicts.")
