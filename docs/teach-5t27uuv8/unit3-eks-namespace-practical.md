# Unit 3 Practical: Deploy on Amazon EKS in Your Own Namespace

**Format:** stand-alone practical on real Amazon EKS, done from the AWS console and AWS CloudShell  
**Who does what:** you prepare and check access in the console; each student deploys, inspects, scales, exposes and cleans up in **their own namespace**  
**Prerequisite for students:** none beyond Kubernetes basics; useful after the [3.2 lecture](unit3-topic2-lecture.md)

!!! teacher "Separate from the lectures and labs"
    This practical stands on its own. It does not replace any lecture segment, and it does not touch the Floci labs (Lab 07 and Lab 08 use namespace `usms` on Floci, not this cluster) or the lecture practice namespaces `u3t1`, `u3t2`, `u3t3`. Students work only in their assigned namespaces on the real cluster.

!!! warning "Keep the student list out of this repository"
    The repository is public. Keep IAM usernames and the username-to-namespace list in ClassLegend or a local file, never on this page.

## Before the practical: check access in the console

The IAM users and the student namespaces already exist. These steps confirm the rest is in place, all from the AWS console in the cluster's Region.

**Step 1: Cluster and capacity.** **Elastic Kubernetes Service**, then your cluster: status **Active**. Open **Compute**, then the node group, and check its size.

- 23 students × 3 replicas is up to 69 Pods. A `t3.medium` node holds at most 17 Pods, about 14 after system Pods, so 2 nodes are far too few.
- Either **Edit** the node group to **desired 6, maximum 6** (`t3.medium`), or create a node group of **3 × `t3.large`** (35 Pods each). Wait until the nodes are **Ready**.
- Bigger capacity costs more per hour. Scale it back down, or delete it, the same day.

**Step 2: Students can open CloudShell and reach the cluster.** **IAM**, then **User groups** (for example `EKS-Students`), then **Permissions**:

- `AWSCloudShellFullAccess` attached, so students can open CloudShell.
- An inline policy allowing only `eks:DescribeCluster` and `eks:ListClusters` (needed by `aws eks update-kubeconfig`). In the console: **Add permissions**, **Create inline policy**, **JSON**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["eks:DescribeCluster", "eks:ListClusters"],
      "Resource": "*"
    }
  ]
}
```

- No `AdministratorAccess` and no other `eks:*` actions on any student user or group.

**Step 3: One access entry per student, scoped to their namespace.** EKS cluster, then **Access**. The authentication mode must include **EKS API**. For each student, check (or create) an access entry:

1. **Create access entry**, then **IAM principal ARN**: the student's IAM user. **Type:** Standard. **Next**.
2. **Policy name:** `AmazonEKSEditPolicy`. **Access scope:** **Kubernetes namespace**, then the student's namespace. **Add policy**, **Next**, **Create**.

The student can then create, scale and delete workloads in their namespace and nowhere else. They cannot list nodes or other namespaces; that is expected.

**Step 4: Resource defaults (only if the namespaces have quotas).** If your namespaces have a `ResourceQuota` on CPU or memory, the students' one-line `kubectl create deployment` is rejected unless the namespace also has a `LimitRange` that supplies default requests and limits. Check in the console: cluster, **Resources**, **Policy**, **Limit Ranges** and **Resource Quotas**, filtered by namespace. The console cannot create these; if one is missing, apply it once per namespace from CloudShell as the cluster admin:

```bash
NS=student-a   # repeat for each student namespace

kubectl apply -n "$NS" -f - <<'EOF'
apiVersion: v1
kind: LimitRange
metadata:
  name: defaults
spec:
  limits:
    - type: Container
      defaultRequest: { cpu: 50m, memory: 64Mi }
      default: { cpu: 200m, memory: 128Mi }
EOF
```

A quota with `services.loadbalancers: "0"` also enforces lab rule 3 (no public load balancers), because `AmazonEKSEditPolicy` itself allows `LoadBalancer` Services.

**Step 5: Test one student.** In a private browser window, sign in as one student (no administrator rights), open CloudShell, and run handout Steps 2 to 4 and 8. Then run `kubectl get pods -n kube-system`: it must return `Forbidden`.

**Instructor readiness checklist**

- [ ] Cluster **Active**; node group sized for 23 students (Step 1)
- [ ] Your own `kubectl` works with cluster admin access
- [ ] Authentication mode includes **EKS API** (access entries)
- [ ] All 23 student namespaces exist
- [ ] Student IAM group has CloudShell access and only the restricted EKS policy
- [ ] Every student has a namespace-scoped access entry with `AmazonEKSEditPolicy`
- [ ] Namespaces with quotas also have a LimitRange
- [ ] One student tested successfully without `AdministratorAccess`
- [ ] `AdministratorAccess` removed from all student identities
- [ ] Region and cluster name in the handout match your cluster

## Student handout

Copy this section into your LMS or class group. Confirm the cluster name and Region first, and give each student their namespace name.

### DSO303 Amazon EKS student lab

**Objective:** connect to our shared Amazon EKS cluster from AWS CloudShell, deploy a containerised application with `kubectl`, inspect it, scale it, expose it inside the cluster, and clean up. You have your own Kubernetes namespace; do every task inside it.

**Step 1: Sign in to AWS**

1. Sign in to the AWS Management Console with your assigned IAM username and password.
2. Select the **Asia Pacific (Mumbai)** Region (`ap-south-1`).
3. Open **AWS CloudShell** from the icon in the console's top bar.
4. Confirm your identity, and check the ARN ends with your assigned IAM username:

```bash
aws sts get-caller-identity
```

!!! note

    *What do you observe? and What do you think each of those values Mean/*

    UserId — The unique identifier of the IAM user or assumed role session.

    Account — The 12-digit AWS account ID.

    Arn — The Amazon Resource Name identifying the current IAM user or assumed role.

**Step 2: Connect to the EKS cluster**

```bash
aws eks update-kubeconfig --name dso303-u3-shared --region ap-south-1
```

This writes the cluster's address and how to authenticate into your kubeconfig, so `kubectl` can reach it. Your instructor confirms the cluster name before the lab.

**Step 3: Use your assigned namespace**

Your instructor gives you your namespace, for example IAM user `StudentA` uses namespace `student-a`. Replace `student-a` below with yours:

1. Check all the namespace : K get ns
2. identify your namespace

```bash
kubectl config set-context --current --namespace=student-a
kubectl config view --minify
```
what is the short anme for namespace?

Check that the context shows your namespace.

**Step 4: Create a Deployment**

Name nginx, and image nginx:apline replica=1 ad verify it

```bash
kubectl create deployment nginx --image=nginx:alpine --replicas=2
kubectl get deployments
kubectl get pods
```

**Step 5: Inspect your Pods**

```bash
kubectl describe deployment nginx
kubectl get pods -o wide
```

Look at the Pod status, the node each Pod runs on, its IP address, and the replica count.

**Step 6: Scale to three replicas**

```bash
kubectl scale deployment nginx --replicas=3
kubectl get pods
```

You should see three Pods once the Deployment is ready.

**Step 7: Expose the Deployment inside the cluster**

```bash
kubectl expose deployment nginx --port=80 --target-port=80 --type=ClusterIP
kubectl get services
kubectl describe service nginx
```

A `ClusterIP` Service is reachable only from inside the cluster; it does not create a public internet endpoint.

**Step 8: Clean up**

```bash
kubectl delete deployment nginx
kubectl delete service nginx
kubectl get deployments
kubectl get services
```

Both lists should be empty.

**Lab rules**

1. Always work inside your assigned namespace.
2. Do not access or change another student's resources.
3. Do not create `LoadBalancer` Services unless the instructor approves.
4. Delete your workloads when you finish.
5. Do not try to change the cluster's access or security settings.
6. Report permission errors to the instructor; do not try to get around them.

**Submission:** screenshots or terminal output showing your connection to EKS, your namespace, the Deployment created, Pods running, scaling from two to three replicas, the `ClusterIP` Service, and the clean-up. Include your IAM username and namespace.

## Expected errors and what they mean

| Student sees | Meaning | Fix |
| --- | --- | --- |
| CloudShell does not open | No CloudShell permission | Check the student group has `AWSCloudShellFullAccess` (Step 2) |
| `AccessDeniedException` on `update-kubeconfig` | IAM user lacks `eks:DescribeCluster` | Check the inline policy (Step 2) |
| `error: You must be logged in to the server (Unauthorized)` | No access entry for this IAM user | Add the access entry (Step 3) |
| `Forbidden` on `get pods` | Wrong namespace in the context, or the access policy is scoped to another namespace | Re-run handout Step 3 with the correct namespace; check Step 3 above |
| `exceeded quota` or `failed quota: must specify limits` | Quota without a LimitRange, or too many Pods | Add the LimitRange (Step 4), or scale down |
| Pods stay `Pending` | Node group out of room | Scale the node group (Step 1) |

## After the practical

1. In the console, cluster, **Resources**, **Workloads**, filter each student namespace (or all namespaces): no `nginx` Deployments or Services left. Remove any leftovers from CloudShell with `kubectl delete deployment,service nginx -n <namespace>`.
2. Scale the node group back down (or delete it) so the extra capacity stops billing.
3. If the cluster is not needed for a lecture, delete it as in [Shared EKS cluster: After class](unit3-shared-eks-cluster.md#after-class-delete-everything).

!!! info "Later labs that need more access"
    Keep this namespace-scoped setup for deployment labs. For cluster administration, node management or cluster-wide RBAC, use a separate training cluster or a supervised, temporary elevated-access arrangement, rather than giving 23 users wide control of the shared cluster.
