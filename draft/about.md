!!! example "code implementation"

    === "C"

        ```c
          #include <stdio.h>
          #include <stdlib.h>

          #define n 3 // taking it as 3 for example

          //define the function for square matrix multiplication
          void squareMatrixMultiply(int A[n][n], int B[n][n], int C[n][n]){
            for (int i=0; i<n; i++){
                for (int j=0; j<n; j++){
                    C[i][j] = 0;
                    for (int k=0; k< n; k++){
                        C[i][j] = C[i][j]+A[i][k]*B[k][j];
                    }
                }
            }

          }

          int main(void) {
            int A[n][n] = {{1,2,3}, {4,5,6},{7,8,9}};
            int B[n][n] = {{1,2,3},{4,5,6},{7,8,9}}
            int C[n][n]

            printf("Result:\n");
            for (int i = 0; i < N; i++) {
                for (int j = 0; j < N; j++) {
                    printf("%d ", C[i][j]);
                }
                printf("\n");
                }
            return 0;
            }
        ```

    === "C++"

        ```c++
            #include <iostream>
            #include <vector>
            using namespace std;

            #define N 3

            void multiply(vector<vector<int>>& A, vector<vector<int>>& B, vector<vector<int>>& C) {
                for (int i = 0; i < N; i++) {
                    for (int j = 0; j < N; j++) {
                        C[i][j] = 0;
                        for (int k = 0; k < N; k++) {
                            C[i][j] += A[i][k] * B[k][j];
                        }
                    }
                }
            }

            int main() {
                vector<vector<int>> A = {{1,2,3},{4,5,6},{7,8,9}};
                vector<vector<int>> B = {{9,8,7},{6,5,4},{3,2,1}};
                vector<vector<int>> C(N, vector<int>(N));

                multiply(A, B, C);

                cout << "Result:\n";
                for (auto &row : C) {
                    for (auto &val : row) cout << val << " ";
                    cout << endl;
                }
            }

        ```
    === "JS"

        ```js
            function multiply(A, B) {
            const n = A.length;
            let C = Array.from({ length: n }, () => Array(n).fill(0));

            for (let i = 0; i < n; i++) {
                for (let j = 0; j < n; j++) {
                    for (let k = 0; k < n; k++) {
                     C[i][j] += A[i][k] * B[k][j];
                    }
                }
             }
            return C;

            }

            const A = [[1,2,3],[4,5,6],[7,8,9]];
            const B = [[9,8,7],[6,5,4],[3,2,1]];

            console.log("Result:");
            console.log(multiply(A, B));

        ```
    === "Java"

        ```java
            public class MatrixMultiply {
                public static void multiply(int[][] A, int[][] B, int[][] C, int n) {
                    for (int i = 0; i < n; i++) {
                        for (int j = 0; j < n; j++) {
                C[i][j] = 0;
                            for (int k = 0; k < n; k++) {
                                C[i][j] += A[i][k] * B[k][j];
                            }
                        }
                    }
                }

            public static void main(String[] args) {
                int n = 3;
                int[][] A = {{1,2,3},{4,5,6},{7,8,9}};
                int[][] B = {{9,8,7},{6,5,4},{3,2,1}};
                int[][] C = new int[n][n];

                multiply(A, B, C, n);

                System.out.println("Result:");
                for (int[] row : C) {
                    for (int val : row) {
                        System.out.print(val + " ");
                    }
                    System.out.println();
                }
            }
        }


        ```



    === "py"

        ```py
            def multiply(A, B):
                n = len(A)
                C = [[0]*n for _ in range(n)]
                for i in range(n):
                    for j in range(n):
                        for k in range(n):
                            C[i][j] += A[i][k] * B[k][j]
                return C

            A = [[1,2,3],[4,5,6],[7,8,9]]
            B = [[9,8,7],[6,5,4],[3,2,1]]

            C = multiply(A, B)

            print("Result:")
            for row in C:
            print(row)

        ```
