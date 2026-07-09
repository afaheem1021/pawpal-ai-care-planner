# PawPal+ Project Reflection

## 1. System Design

Three of the core actions for the app are to be able to manage/edit pet infromation, making tasks to-do, and generating/viewing the plan. 

**a. Initial design**

- Briefly describe your initial UML design.
- What classes did you include, and what responsibilities did you assign to each?

Created 4 classes Task, Pet, Owner, and Scheduler. The Owner holds Pets. Each Pet their list of their specific Tasks. The Task class acts as "database" for care activities. The Scheduler is the brain of our application  pulling data from the Owner to compile, sort, and check for conflicts to generate a master daily schedule.


**b. Design changes**

- Did your design change during implementation?
- If yes, describe at least one change and why you made it.

Yes, the design changed after the AI review revealed several logic errors that would break the Scheduler's functionality, the AI fixed the sorting errors, the AI pointed out that sorting time and priority as simple strings fails, to fix the error the scheduler needs to parse times using datetime for priority rankings 


---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?
- How did you decide which constraints mattered most?

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

Our conflict detection (`check_conflicts`) compares every pair of tasks with a simple nested loop, which is O(n^2). The AI showed me a fancier alternative (sorting once and only comparing neighbors, or using `itertools.combinations`), but we kept the explicit nested loop because it is easier to read and explain, and a pet owner realistically has dozens of tasks per day, not thousands, so the performance difference is invisible. A related tradeoff: the scheduler treats ALL tasks as competing for the owner's time, so two tasks for two different pets at the same time still count as a conflict — that matches reality (one human does all the tasks), but it means we can't model two family members splitting the work. Finally, our recurring logic approximates "monthly" as exactly 30 days instead of handling real calendar months, which keeps the `timedelta` math simple at the cost of drifting a day or two over time.

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
