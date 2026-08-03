# 7.3 Huffman Coding

## 7.3.1 Introduction to data compression

**What is Data Compression?**

- The process of encoding information using fewer bits than the original representation.

**Why Compress Data?**

- Reduce storage space
- Faster transmission over networks
- More efficient processing

**Types of Data compression**

<div class="custom-table-container">
  <table class="custom-table">
    <thead>
      <tr>
        <th>Type</th>
        <th>Description</th>
        <th>Examples</th>
      </tr>
    </thead>
    <tbody>
      <tr>
      <td>Lossless</td>
        <td> No data is lost; original data can be perfectly reconstructed.</td>
        <td>Huffman coding, Run-length encoding, Lempel-Ziv (ZIP files).</td>
      </tr>
      <tr>
      <td>Lossy</td>
        <td>Some data is lost; approximate reconstruction is acceptable.</td>
        <td>JPEG (images), MP3 (audio), MPEG (video).</td>
      </tr>
    </tbody>
  </table>
</div>

**Fixed-length vs Variable-length Codes:**

- **Fixed-length**: Each character uses same number of bits (e.g., ASCII - 8 bits per character)
- **Variable-length**: Frequent characters use shorter codes, rare characters use longer codes

!!! note ""

     Use shorter codes for frequent characters and longer codes for rare characters to reduce the total number of bits used.

## 7.3.2 Huffman's greedy algorithm for optimal prefix codes

**Prefix Codes:**

- No codeword is a prefix of any other codeword
- Enables unambiguous decoding without lookahead
- Example: If 'A' = 0, then no other code can start with 0

**Huffman's Greedy Strategy:**

- **Greedy Choice**: Always merge the two least frequent nodes
- **Optimal Substructure**: Optimal solution contains optimal solutions to subproblems

**Algorithm Steps:**

1.  Calculate frequency of each character
2.  Arrange in increasing order of their frequency
3.  Create a leaf node for each character with its frequency
4.  While more than one node exists:

    - Remove two nodes with smallest frequencies
    - Create a new internal node with these two as children
    - Frequency of new node = sum of children's frequencies
    - Insert new node back into the set

5.  The remaining node is the root of the Huffman tree
6.  Assign 0 for left edge, 1 for right edge.
7.  Concatenate bits from root to leaf to form each symbol’s code.
8.  Total expected Code Length
    $$ cost = \sum\_{i=1}^{n} {f(a_i)} \times {L(a_i)} $$
    where $f(a_i)$ is the frequence of $a_i$ and $L(a_i)$ is the length for $a_i$

## 7.3.3 Building Huffman trees

!!! example "Building Huffman Tree"

    **Example: Encode "CCCFFIICCFFLL"**

    **Step 1: Calculate Frequencies**

    ```
    Character: C, F, I, L
    Frequency: C=5, F=4, I=2, L=2
    ```

    **Step 2: Rearranging in increaing order of frequency**

      I=2, L=2, F=4, C=5


    **Step 3: Build the Tree**

    ```mermaid
    graph TD
    R((13))
    X2((8))
    X1((4))
    I((I:2))
    L((L:2))
    F((F:4))
    C((C:5))


    R -->|0| X2
    R -->|1| C
    X2 -->|0| X1
    X2 -->|1| F
    X1 -->|0| I
    X1 -->|1| L

    ```

    **Step 3: Assign Codes**
    Traverse the tree: left = 0, right = 1 from the root

    ```

    I : 000
    L : 001
    F : 01
    C : 1

    ```

    **Encoding "CCCFFIICCFFLL":**

    | Element | bits | Size |
    | --- | --- | --- |
    | I | 000 | $3 \times 2 = 5 $ |
    | L | 001 | $2 \times 4 = 8 $ |
    | F | 01 | $3 \times 2 = 6 $ |
    | C | 1 | $3 \times 2 = 6 $ |
    |  | Total | 25 |

    Step 4: Compressed Size

    - Total bits: $25$ bits
    - Characters: $4 \times 8 = 32$ bits (each character is 8 bits)
    - Table: 9 bits (user for decoding, need to pass the table as well)
    - Total Compressed size: $25 + 9 + 32 = 66 bits$

!!! example "Building Huffman Tree Example : 2"

    **Example: Encode "BCCA BBDD AECC BBAE DDCC"**

    **Step 1: Calculate Frequencies**

    ```
    Character: A, B, C, D, E
    Frequency: A = 3, B = 5, C = 6 D = 4, E = 2
    ```
    **Step 2: Rearranging in increaing order of frequency**

      E = 2, A=3, D=4, B=5, C=6

    **Step 3: Build the Tree**

    ```mermaid
    graph BT
    R((20))
    X1((9))
    X2((5))
    X3((11))

    E((E:2))
    A((A:3))
    D((D:4))
    B((B:5))
    C((C:6))

    E -->|0| X2
    A -->|1| X2
    X2 -->|0| X1
    D -->|1| X1
    B -->|0| X3
    C -->|1| X3
    X1 -->|0| R
    X3 -->|1| R

    ```


    **Step 3: Assign Codes**
    Traverse the tree from the root

    ```
    A : 001
    B : 10
    C : 11
    D : 01
    E : 000

    ```

    **Encoding "BCCA BBDD AECC BBAE DDCC":**

    | Element | bits | Size |
    | --- | --- | --- |
    | A | 001 | $3 \times 3 = 9 $ |
    | B | 10 | $2 \times 5 = 10 $ |
    | c | 11 | $6 \times 2 = 12 $ |
    | D | 01 | $4 \times 2 = 8 $ |
    | E | 000 | $3 \times 2 = 6 $ |
    |  | Total | 45 |

    Step 4: Compressed Size

    - Total bits: $45$ bits
    - Characters: $5 \times 8 = 40$ bits (each character is 8 bits)
    - Table: 12 bits (user for decoding, need to pass the table as well)
    - Total Compressed size: $45 + 12 + 40 = 97 bits$

!!! example "Building Huffman Tree Example : 3, when Probability is given"

    {{image_block("../img/u7gdy/huffman.png", "Huffman", "Huffman", "", "", size="large")}}
    **E = 0.3, B=0.25, A=0.25, C=0.15, D=0.05** (Arrange it in decreasing order)

!!! tip "Tip"

    In Huffman coding, which is used for data compression, the most frequently appearing element is encoded with the least number of bits and vice versa.

### **Code Implementation**

```python
import heapq
import os

class HuffmanNode:
    def __init__(self, char, freq):
        self.char = char
        self.freq = freq
        self.left = None
        self.right = None

    # For heap comparison
    def __lt__(self, other):
        return self.freq < other.freq

class HuffmanCoding:
    def __init__(self):
        self.heap = []
        self.codes = {}
        self.reverse_mapping = {}

    def calculate_frequency(self, text):
        """Calculate frequency of each character in text"""
        frequency = {}
        for char in text:
            if char not in frequency:
                frequency[char] = 0
            frequency[char] += 1
        return frequency

    def make_heap(self, frequency):
        """Create a min heap of Huffman nodes"""
        for char, freq in frequency.items():
            node = HuffmanNode(char, freq)
            heapq.heappush(self.heap, node)

    def merge_nodes(self):
        """Build Huffman tree by merging nodes"""
        while len(self.heap) > 1:
            # Pop two nodes with smallest frequency
            node1 = heapq.heappop(self.heap)
            node2 = heapq.heappop(self.heap)

            # Merge them
            merged = HuffmanNode(None, node1.freq + node2.freq)
            merged.left = node1
            merged.right = node2

            heapq.heappush(self.heap, merged)

    def make_codes_helper(self, root, current_code):
        """Recursively generate Huffman codes"""
        if root is None:
            return

        # Leaf node - contains a character
        if root.char is not None:
            self.codes[root.char] = current_code
            self.reverse_mapping[current_code] = root.char
            return

        # Traverse left and right
        self.make_codes_helper(root.left, current_code + "0")
        self.make_codes_helper(root.right, current_code + "1")

    def make_codes(self):
        """Generate Huffman codes from the tree"""
        root = heapq.heappop(self.heap)
        current_code = ""
        self.make_codes_helper(root, current_code)

    def encode(self, text):
        """Encode text using Huffman coding"""
        # Build the Huffman tree
        frequency = self.calculate_frequency(text)
        self.make_heap(frequency)
        self.merge_nodes()
        self.make_codes()

        # Encode the text
        encoded_text = ""
        for char in text:
            encoded_text += self.codes[char]

        return encoded_text

    def decode(self, encoded_text):
        """Decode Huffman encoded text"""
        current_code = ""
        decoded_text = ""

        for bit in encoded_text:
            current_code += bit
            if current_code in self.reverse_mapping:
                char = self.reverse_mapping[current_code]
                decoded_text += char
                current_code = ""

        return decoded_text

# Example usage
if __name__ == "__main__":
    # Example 1: Simple text
    text = "HUFFMAN"
    print(f"Original text: {text}")

    huffman = HuffmanCoding()
    encoded = huffman.encode(text)
    print(f"Encoded: {encoded}")

    decoded = huffman.decode(encoded)
    print(f"Decoded: {decoded}")

    # Compression statistics
    original_size = len(text) * 8  # Assuming 8-bit ASCII
    compressed_size = len(encoded)
    compression_ratio = (1 - compressed_size / original_size) * 100

    print(f"\nOriginal size: {original_size} bits")
    print(f"Compressed size: {compressed_size} bits")
    print(f"Compression ratio: {compression_ratio:.2f}%")

    # Example 2: Show codes
    print(f"\nHuffman Codes:")
    for char, code in huffman.codes.items():
        print(f"  '{char}': {code}")
```

### **7.3.4 Analysis of Huffman Coding and Its Optimality**

**Time Complexity:**

- **Building frequency table**: O(n) where n = text length
- **Building min-heap**: O(k) where k = number of unique characters
- **Building Huffman tree**: O(k log k) - k extractions from heap
- **Generating codes**: O(k) - tree traversal
- **Encoding/Decoding**: O(n)

**Total: O(n + k log k)**

**Space Complexity:**

- O(k) for the Huffman tree and code mappings
- O(n) for the encoded text

**Proof of Optimality:**

**Lemma 1:** Huffman codes are prefix codes

- By construction, all characters are at leaves
- No code is a prefix of another

**Lemma 2:** The two least frequent characters have the longest codes and differ only in the last bit

- In the greedy choice, they are merged last and become siblings

**Theorem:** Huffman coding produces an optimal prefix code

**Proof by Exchange Argument:**

1. Let x and y be the two least frequent characters
2. In any optimal code, x and y have the longest codes (can be proved by contradiction)
3. We can swap x and y with the longest codes in any optimal solution without increasing cost
4. Therefore, putting x and y as siblings (as Huffman does) is optimal

**Why Huffman is Optimal:**

- It always makes the locally optimal choice (merge least frequent)
- The problem exhibits optimal substructure
- No other prefix code can achieve better compression for the given frequencies

### **Teaching Examples**

**Example 1: "MISSISSIPPI"**

```
Frequencies: M=1, I=4, S=4, P=2
Expected codes: I and S get short codes, M gets long code
```

**Example 2: "AAAAA" (All same character)**

```
Frequency: A=5
Code: A=0 (or 1)
Compression: 5 bits vs 40 bits (87.5% savings!)
```

**Example 3: "ABCDE" (All different, equal frequency)**

```
All characters get codes of similar length
Minimal compression possible
```

### **Practical Applications**

1. **ZIP compression** (DEFLATE algorithm)
2. **JPEG images** (after quantization)
3. **MP3 audio compression**
4. **PDF files**
5. **Network protocols**

**Key Insights:**

- Huffman coding is the **optimal prefix code** for given frequencies
- The greedy approach works because of the optimal substructure
- Real compression systems often use Huffman as one stage in a pipeline
- For best compression, we need good frequency estimates
