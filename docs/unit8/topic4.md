# Activity Selection Problems

The Activity Selection Problem is a classic optimization problem that demonstrates the power of greedy algorithms. It involves selecting the maximum number of non-overlapping activities from a set, making it fundamental to scheduling and resource allocation.

## 7.4.1 Problem formulation and real-world applications

Given n activities with start times $s_i$ and finish times $f_i$, select the maximum number of activities that don't overlap, assuming a single resource that can only be used by one activity at a time.

Given:

- n activities with:

      - start[i] → start time of activity i
      - finish[i] → finish time of activity i

Objective:

Select the maximum number of activities that can be performed by a single person or machine, assuming that a person can work on only one activity at a time.

**Application**

| Domain                                  | Description                                                                                |
| --------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Scheduling**                          | Scheduling jobs, meetings, or classes in limited resources (e.g., classrooms or machines). |
| **Resource Allocation**                 | Assigning processors to non-overlapping tasks in multiprocessor systems.                   |
| **Event Management**                    | Planning non-conflicting events in a venue.                                                |
| **CPU Job Scheduling**                  | Selecting processes to execute when each has a time window.                                |
| **Airline Runways / Sports Scheduling** | Maximizing the number of non-overlapping flights or matches.                               |

## 7.4.2 Greedy approach to activity selection

The Greedy Strategy is: To fit maximum activities, always pick the activity that finishes earliest —
this leaves maximum room for future activities.

Steps (Greedy Strategy)

1.  Sort all activities in increasing order of finish time.

2.  Select the first activity (it finishes earliest).

3.  For each subsequent activity:

    - If its start time ≥ finish time of the previously selected activity, select it.
    - Continue until all activities are checked.

!!! example "Example"

    | Activity | Start | Finish |
    | -------- | ----- | ------ |
    | A1       | 1     | 2      |
    | A2       | 3     | 4      |
    | A3       | 0     | 6      |
    | A4       | 5     | 7      |
    | A5       | 8     | 9      |
    | A6       | 5     | 9      |

    - Step 1: Sort by finish time (already sorted here).
    - Step 2: Pick A1 (finishes at 2).
    - Step 3: Next activity with start ≥ 2 is A2.
    - Step 4: Next with start ≥ 4 is A4.
    - Step 5: Next with start ≥ 7 is A5.

     - Selected = {A1, A2, A4, A5}
     → Maximum = 4 activities

Time Complexity is O(n log n)

<!-- ## 7.4.3 Proof of correctness

## 7.4.4 Variations and extensions of the problem -->
