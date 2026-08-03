## Problem 1: Dinner Table Arrangements

You're organizing a dinner party with N friends (1 ≤ N ≤ 20). Each friend has allergies represented as a bitmask. You need to arrange them around a table such that no two adjacent persons share any common allergy.

**Input Format:**

- First line: T (number of test cases)
- For each test case:
  - First line: N (number of friends)
  - Next N lines: Each contains M (number of allergies) followed by M integers representing allergy IDs (1-30)

**Output Format:**
For each test case, output "YES" if valid arrangement exists, "NO" otherwise.

**Sample Input:**

```
2
3
2 1 2
2 2 3
1 3
4
2 1 2
1 2
1 3
1 4
```

**Sample Output:**

```
YES
NO
```

**Constraints:**

- 1 ≤ T ≤ 10
- 1 ≤ N ≤ 20
- 1 ≤ M ≤ 10

---

## Problem 2: Maximum AND Subarray

Given an array of N integers (1 ≤ N ≤ 10^5), find the maximum possible value of AND of any subarray of length exactly K.

**Input Format:**

- First line: T (1 ≤ T ≤ 10)
- For each test case:
  - First line: N K
  - Second line: N integers A[i] (0 ≤ A[i] ≤ 10^9)

**Output Format:**
For each test case, output the maximum AND value.

**Sample Input:**

```
2
5 3
12 8 15 10 7
4 2
16 16 16 16
```

**Sample Output:**

```
8
16
```

**Hint:** Think about checking bits from MSB to LSB.

## Problem 3: Sliding Window Maximum

Given an array of N integers and a window size K, find the maximum in each sliding window of size K.

**Input Format:**

- First line: N K
- Second line: N space-separated integers A[i] (-10^9 ≤ A[i] ≤ 10^9)

**Output Format:**
Print N-K+1 numbers - the maximum of each window.

**Sample Input:**

```
8 3
1 3 -1 -3 5 3 6 7
```

**Sample Output:**

```
3 3 5 5 6 7
```

## Problem 4: Maximum in Sliding Window with Updates

You have an array of N elements. Process Q queries of two types:

- Type 1: Update A[pos] = val
- Type 2: Query maximum in sliding window of size K ending at index i

**Input Format:**

- First line: N K Q
- Second line: Initial array of N integers
- Next Q lines: Each query (type parameters)

**Output Format:**
For each type 2 query, output the maximum.

**Sample Input:**

```
5 3 4
1 2 3 4 5
2 3
1 2 10
2 3
2 5
```

**Sample Output:**

```
3
10
10
```

## Problem 5: Network Latency

Given a network of N routers connected by M bidirectional cables with given latencies, find the minimum latency to send a packet from router 1 to router N.

**Input Format:**

- First line: N M (1 ≤ N ≤ 10^5, 1 ≤ M ≤ 2×10^5)
- Next M lines: u v w (1 ≤ u,v ≤ N, 1 ≤ w ≤ 10^9)

**Output Format:**
Print the minimum latency, or -1 if no path exists.

**Sample Input:**

```
4 4
1 2 5
2 3 3
1 3 8
3 4 2
```

**Sample Output:**

```
10
```

**Path:** 1 → 2 → 3 → 4 (5 + 3 + 2 = 10)

---

In a city, travel time between two intersections depends on the time of day. Given N intersections and M directed roads, each road has a function f(t) = a\*t + b that gives travel time if you start at time t. Find the earliest arrival time at destination N starting from intersection 1 at time 0.

**Input Format:**

- First line: N M
- Next M lines: u v a b (road from u to v with f(t) = a\*t + b)

**Output Format:**
Print earliest arrival time at N (rounded to 2 decimal places) or -1 if unreachable.

**Sample Input:**

```
3 3
1 2 1 0
2 3 1 5
1 3 2 0
```

**Sample Output:**

```
10.00
```

---

## Problem 6: The Shortest Path with Toll Booths

A highway has N toll booths in a line. You start at booth 1 with M coins. At each booth i, you can:

- Pay toll[i] coins and move to next booth (cost: 1 minute)
- Skip the booth (cost: 2 minutes) but can only skip at most K booths in total

Find minimum time to reach booth N.

**Input Format:**

- First line: N M K
- Second line: N integers toll[1..N]

**Output Format:**
Print minimum time or -1 if impossible.

**Sample Input:**

```
5 10 2
3 5 2 4 6
```

**Sample Output:**

```
6
```
