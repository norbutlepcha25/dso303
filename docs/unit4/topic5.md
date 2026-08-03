# Binary Search and Ternary Search

### 4.5.1 Binary Search

Binary search is an efficient **divide-and-conquer** algorithm used to find the position of a target element in a **sorted array**.  
Instead of checking each element sequentially (as in linear search), it repeatedly divides the search space in half, drastically reducing the number of comparisons.

Algorithm:

1. Compare the target element `x` with the middle element of the array.
2. If `x` equals the middle element, return its index.
3. If `x` is smaller, search the left half.
4. If `x` is larger, search the right half.
5. Repeat until the element is found or the range is empty.

!!! example "Example"

    Consider the sorted array: 2 6 8 12 25 56 89 99 and Target = 99

    1. mid = 25 Compare with mid, 25 < 99, Move right
    2. mid = 89, Compare with mid, 89 <99, Move right
    3. Mid = 99, return as 99 = 99

```
BINARY_SEARCH(A, n, x):
    low ← 0
    high ← n - 1
    while low ≤ high:
        mid ← (low + high) / 2
        if A[mid] == x:
            return mid
        else if A[mid] < x:
            low ← mid + 1
        else:
            high ← mid - 1
return -1 // Element not found
```

Time Complexity : O(logn)

### 4.5.2 Ternary Search

Ternary search is another divide-and-conquer technique, similar to binary search.
Instead of dividing the array into two halves, it divides the search space into three parts using two midpoints.

**Algorithm**

- Compute two midpoints:

      - mid1 = low + (high - low) / 3
      - mid2 = high - (high - low) / 3

- Compare the target element x with A[mid1] and A[mid2].
- If x == A[mid1] or x == A[mid2], return that index.
- If x < A[mid1], search the first third.
- If x > A[mid2], search the last third.
- Otherwise, search the middle third.

```
TERNARY_SEARCH(A, low, high, x):
    while low ≤ high:
        mid1 ← low + (high - low) / 3
        mid2 ← high - (high - low) / 3

        if A[mid1] == x:
            return mid1
        if A[mid2] == x:
            return mid2

        if x < A[mid1]:
            high ← mid1 - 1
        else if x > A[mid2]:
            low ← mid2 + 1
        else:
            low ← mid1 + 1
            high ← mid2 - 1
    return -1  // Element not found

```

!!! example "Example"

    A = [1, 3, 5, 7, 9, 11, 13, 15, 17]
    x = 11

    1. low= 1, high = 17

        m1 index =2 value =5, m2 index = 6 value = 13

        compare with m1 and m2, m1 < x < m2

    2. low = 3, high = 5

        m1 index = 3 value = 7, m2 index =5 value = 11, Found

Time Complexity : $O(log_3 n)$
