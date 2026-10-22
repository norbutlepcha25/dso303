"""MkDocs hook: show the official AWS service icon for AWS services.

Applies to the unit notes (docs/unit*/) only, at build time, so the Markdown
stays plain and every note is decorated the same way. Two places get icons,
and nowhere else (body text is never touched):

  - section headings (h2-h6): an icon before each AWS service the heading
    names, e.g. "### AWS CodeCommit";
  - tables in the "Definition" section whose first column lists AWS
    services: a narrow icon column is inserted before the service column.
    A table qualifies when at least half of its body rows start with a
    service name; rows that do not get an empty icon cell.

Icons come from docs/assets/icons/service/ (AWS Architecture Icons). To
support a new service, add a row to SERVICES; names are matched
case-sensitively as whole words, longest name first.
"""

import logging
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.aws_service_icons")

ICON_DIR = "assets/icons/service/"

# icon file stem -> names that refer to that service
SERVICES = {
    # Developer tools
    "aws-code-commit": ["AWS CodeCommit", "CodeCommit"],
    "aws-code-build": ["AWS CodeBuild", "CodeBuild"],
    "aws-code-deploy": ["AWS CodeDeploy", "CodeDeploy"],
    "aws-code-pipeline": ["AWS CodePipeline", "CodePipeline"],
    "aws-code-artifact": ["AWS CodeArtifact", "CodeArtifact"],
    "amazon-code-catalyst": ["Amazon CodeCatalyst", "CodeCatalyst"],
    "amazon-code-guru": ["Amazon CodeGuru", "CodeGuru"],
    "aws-cloud-formation": ["AWS CloudFormation", "CloudFormation"],
    "aws-cloud-development-kit": ["AWS Cloud Development Kit", "Cloud Development Kit", "AWS CDK"],
    "aws-command-line-interface": ["AWS Command Line Interface", "AWS CLI"],
    "aws-management-console": ["AWS Management Console"],
    "aws-cloud-shell": ["AWS CloudShell", "CloudShell"],
    "aws-cloud-control-api": ["AWS Cloud Control API", "Cloud Control API"],
    "aws-infrastructure-composer": ["AWS Infrastructure Composer", "Infrastructure Composer"],
    "aws-proton": ["AWS Proton"],
    "aws-service-catalog": ["AWS Service Catalog", "Service Catalog"],
    "aws-x-ray": ["AWS X-Ray", "X-Ray"],
    "aws-fault-injection-service": ["AWS Fault Injection Service", "Fault Injection Service", "AWS FIS"],
    # Compute and containers
    "amazon-ec2-auto-scaling": ["Amazon EC2 Auto Scaling", "EC2 Auto Scaling"],
    "aws-application-auto-scaling": ["Application Auto Scaling"],
    "aws-auto-scaling": ["AWS Auto Scaling"],
    "amazon-ec2-image-builder": ["EC2 Image Builder"],
    "amazon-ec2": ["Amazon Elastic Compute Cloud", "Amazon EC2", "EC2"],
    "aws-lambda": ["AWS Lambda", "Lambda"],
    "aws-fargate": ["AWS Fargate", "Fargate"],
    "amazon-ecs-anywhere": ["Amazon ECS Anywhere", "ECS Anywhere"],
    "amazon-elastic-container-service": ["Amazon Elastic Container Service", "Amazon ECS", "ECS"],
    "amazon-eks-anywhere": ["Amazon EKS Anywhere", "EKS Anywhere"],
    "amazon-eks-distro": ["Amazon EKS Distro", "EKS Distro"],
    "amazon-elastic-kubernetes-service": ["Amazon Elastic Kubernetes Service", "Amazon EKS", "EKS"],
    "amazon-elastic-container-registry": ["Amazon Elastic Container Registry", "Amazon ECR", "ECR"],
    "aws-app-runner": ["AWS App Runner", "App Runner"],
    "aws-elastic-beanstalk": ["AWS Elastic Beanstalk", "Elastic Beanstalk"],
    "aws-batch": ["AWS Batch"],
    "amazon-lightsail": ["Amazon Lightsail", "Lightsail"],
    "aws-outposts-family": ["AWS Outposts", "Outposts"],
    "aws-local-zones": ["AWS Local Zones", "Local Zones"],
    "aws-wavelength": ["AWS Wavelength", "Wavelength Zones"],
    "bottlerocket": ["Bottlerocket"],
    "aws-nitro-enclaves": ["AWS Nitro Enclaves", "Nitro Enclaves"],
    "amazon-elastic-inference": ["Amazon Elastic Inference"],
    # Storage
    "amazon-simple-storage-service-glacier": ["Amazon S3 Glacier", "S3 Glacier"],
    "amazon-s3-on-outposts": ["Amazon S3 on Outposts", "S3 on Outposts"],
    "amazon-simple-storage-service": ["Amazon Simple Storage Service", "Amazon S3", "S3"],
    "amazon-elastic-block-store": ["Amazon Elastic Block Store", "Amazon EBS", "EBS"],
    "amazon-efs": ["Amazon Elastic File System", "Amazon EFS", "EFS"],
    "amazon-fsx-for-lustre": ["Amazon FSx for Lustre", "FSx for Lustre"],
    "amazon-fsx-for-net-app-ontap": ["Amazon FSx for NetApp ONTAP", "FSx for NetApp ONTAP"],
    "amazon-fsx-for-open-zfs": ["Amazon FSx for OpenZFS", "FSx for OpenZFS"],
    "amazon-fsx-for-wfs": ["Amazon FSx for Windows File Server", "FSx for Windows File Server"],
    "amazon-fsx": ["Amazon FSx", "FSx"],
    "amazon-file-cache": ["Amazon File Cache"],
    "aws-backup": ["AWS Backup"],
    "aws-storage-gateway": ["AWS Storage Gateway", "Storage Gateway"],
    "aws-data-sync": ["AWS DataSync", "DataSync"],
    "aws-transfer-family": ["AWS Transfer Family", "Transfer Family"],
    "aws-snowball-edge": ["AWS Snowball Edge", "Snowball Edge"],
    "aws-snowball": ["AWS Snowball"],
    "aws-elastic-disaster-recovery": ["AWS Elastic Disaster Recovery", "Elastic Disaster Recovery"],
    # Databases and analytics
    "amazon-rds": ["Amazon Relational Database Service", "Amazon RDS", "RDS"],
    "amazon-aurora": ["Amazon Aurora", "Aurora"],
    "amazon-dynamo-db": ["Amazon DynamoDB", "DynamoDB"],
    "amazon-elasti-cache": ["Amazon ElastiCache", "ElastiCache"],
    "amazon-memory-db": ["Amazon MemoryDB", "MemoryDB"],
    "amazon-neptune": ["Amazon Neptune", "Neptune"],
    "amazon-redshift": ["Amazon Redshift", "Redshift"],
    "amazon-document-db": ["Amazon DocumentDB", "DocumentDB"],
    "amazon-keyspaces": ["Amazon Keyspaces"],
    "amazon-timestream": ["Amazon Timestream", "Timestream"],
    "aws-database-migration-service": ["AWS Database Migration Service", "Database Migration Service", "AWS DMS"],
    "amazon-athena": ["Amazon Athena", "Athena"],
    "aws-glue": ["AWS Glue"],
    "amazon-emr": ["Amazon EMR"],
    "aws-lake-formation": ["AWS Lake Formation", "Lake Formation"],
    "amazon-open-search-service": ["Amazon OpenSearch Service", "OpenSearch Service", "Amazon OpenSearch", "OpenSearch"],
    "amazon-quick": ["Amazon Quick Suite", "Amazon QuickSight", "QuickSight"],
    "amazon-kinesis-data-streams": ["Amazon Kinesis Data Streams", "Kinesis Data Streams"],
    "amazon-kinesis-video-streams": ["Amazon Kinesis Video Streams", "Kinesis Video Streams"],
    "amazon-data-firehose": ["Amazon Data Firehose", "Amazon Kinesis Data Firehose", "Kinesis Data Firehose", "Data Firehose", "Firehose"],
    "amazon-managed-service-for-apache-flink": ["Amazon Managed Service for Apache Flink", "Managed Service for Apache Flink"],
    "amazon-kinesis": ["Amazon Kinesis", "Kinesis"],
    "amazon-managed-streaming-for-apache-kafka": ["Amazon Managed Streaming for Apache Kafka", "Amazon MSK", "MSK"],
    "amazon-managed-workflows-for-apache-airflow": ["Amazon Managed Workflows for Apache Airflow", "Amazon MWAA"],
    # Application integration
    "amazon-simple-queue-service": ["Amazon Simple Queue Service", "Amazon SQS", "SQS"],
    "amazon-simple-notification-service": ["Amazon Simple Notification Service", "Amazon SNS", "SNS"],
    "amazon-event-bridge": ["Amazon EventBridge", "EventBridge"],
    "amazon-mq": ["Amazon MQ"],
    "aws-step-functions": ["AWS Step Functions", "Step Functions"],
    "aws-express-workflows": ["Express Workflows"],
    "aws-app-sync": ["AWS AppSync", "AppSync"],
    "amazon-api-gateway": ["Amazon API Gateway", "API Gateway"],
    "amazon-simple-email-service": ["Amazon Simple Email Service", "Amazon SES"],
    "aws-app-config": ["AWS AppConfig", "AppConfig"],
    # Networking and content delivery
    "amazon-vpc-lattice": ["Amazon VPC Lattice", "VPC Lattice"],
    "amazon-virtual-private-cloud": ["Amazon Virtual Private Cloud", "Amazon VPC", "VPC"],
    "amazon-route-53": ["Amazon Route 53", "Route 53"],
    "amazon-application-recovery-controller": ["Amazon Application Recovery Controller", "Application Recovery Controller"],
    "amazon-cloud-front": ["Amazon CloudFront", "CloudFront"],
    "elastic-load-balancing": [
        "Elastic Load Balancing", "Application Load Balancer", "Network Load Balancer",
        "Gateway Load Balancer", "Classic Load Balancer", "ELB", "ALB", "NLB", "GWLB",
    ],
    "aws-global-accelerator": ["AWS Global Accelerator", "Global Accelerator"],
    "aws-transit-gateway": ["AWS Transit Gateway", "Transit Gateway"],
    "aws-direct-connect": ["AWS Direct Connect", "Direct Connect"],
    "aws-site-to-site-vpn": ["AWS Site-to-Site VPN", "Site-to-Site VPN"],
    "aws-client-vpn": ["AWS Client VPN", "Client VPN"],
    "aws-private-link": ["AWS PrivateLink", "PrivateLink"],
    "aws-cloud-map": ["AWS Cloud Map", "Cloud Map"],
    "aws-app-mesh": ["AWS App Mesh", "App Mesh"],
    "aws-cloud-wan": ["AWS Cloud WAN", "Cloud WAN"],
    "aws-verified-access": ["AWS Verified Access", "Verified Access"],
    "elastic-fabric-adapter": ["Elastic Fabric Adapter"],
    # Security, identity and compliance
    "aws-iam-identity-center": ["AWS IAM Identity Center", "IAM Identity Center"],
    "aws-identity-and-access-management": ["AWS Identity and Access Management", "Identity and Access Management", "AWS IAM", "IAM"],
    "aws-organizations": ["AWS Organizations"],
    "aws-control-tower": ["AWS Control Tower", "Control Tower"],
    "aws-key-management-service": ["AWS Key Management Service", "Key Management Service", "AWS KMS", "KMS"],
    "aws-secrets-manager": ["AWS Secrets Manager", "Secrets Manager"],
    "aws-certificate-manager": ["AWS Certificate Manager", "Certificate Manager", "ACM"],
    "aws-private-certificate-authority": ["AWS Private Certificate Authority", "AWS Private CA"],
    "aws-cloud-hsm": ["AWS CloudHSM", "CloudHSM"],
    "aws-waf": ["AWS WAF", "WAF"],
    "aws-shield": ["AWS Shield Advanced", "AWS Shield", "Shield Advanced", "Shield Standard"],
    "aws-firewall-manager": ["AWS Firewall Manager", "Firewall Manager"],
    "aws-network-firewall": ["AWS Network Firewall", "Network Firewall"],
    "amazon-guard-duty": ["Amazon GuardDuty", "GuardDuty"],
    "amazon-inspector": ["Amazon Inspector"],
    "amazon-macie": ["Amazon Macie", "Macie"],
    "amazon-detective": ["Amazon Detective"],
    "aws-security-hub": ["AWS Security Hub", "Security Hub"],
    "amazon-security-lake": ["Amazon Security Lake", "Security Lake"],
    "amazon-cognito": ["Amazon Cognito", "Cognito"],
    "amazon-verified-permissions": ["Amazon Verified Permissions", "Verified Permissions"],
    "aws-directory-service": ["AWS Directory Service", "Directory Service"],
    "aws-resource-access-manager": ["AWS Resource Access Manager", "AWS RAM"],
    "aws-signer": ["AWS Signer"],
    "aws-audit-manager": ["AWS Audit Manager", "Audit Manager"],
    "aws-artifact": ["AWS Artifact"],
    # Management, monitoring and governance
    "amazon-cloud-watch": ["Amazon CloudWatch", "CloudWatch"],
    "aws-cloud-trail": ["AWS CloudTrail", "CloudTrail"],
    "aws-config": ["AWS Config"],
    "aws-systems-manager": ["AWS Systems Manager", "Systems Manager"],
    "aws-trusted-advisor": ["AWS Trusted Advisor", "Trusted Advisor"],
    "aws-health-dashboard": ["AWS Health Dashboard", "Personal Health Dashboard", "AWS Health"],
    "aws-well-architected-tool": ["AWS Well-Architected Tool", "Well-Architected Tool"],
    "aws-compute-optimizer": ["AWS Compute Optimizer", "Compute Optimizer"],
    "aws-resilience-hub": ["AWS Resilience Hub", "Resilience Hub"],
    "aws-user-notifications": ["AWS User Notifications"],
    "aws-chatbot": ["AWS Chatbot"],
    "amazon-dev-ops-guru": ["Amazon DevOps Guru", "DevOps Guru"],
    "amazon-managed-grafana": ["Amazon Managed Grafana", "Managed Grafana"],
    "amazon-managed-service-for-prometheus": ["Amazon Managed Service for Prometheus", "Managed Service for Prometheus", "Amazon Managed Prometheus"],
    "aws-distro-for-open-telemetry": ["AWS Distro for OpenTelemetry", "ADOT"],
    "aws-launch-wizard": ["AWS Launch Wizard"],
    "aws-license-manager": ["AWS License Manager"],
    "aws-resource-explorer": ["AWS Resource Explorer"],
    # Cost management
    "aws-cost-explorer": ["AWS Cost Explorer", "Cost Explorer"],
    "aws-budgets": ["AWS Budgets"],
    "aws-cost-and-usage-report": ["AWS Cost and Usage Report", "Cost and Usage Report"],
    "savings-plans": ["Compute Savings Plans", "Savings Plans"],
    "aws-billing-conductor": ["AWS Billing Conductor"],
    # Front-end, migration, ML and other
    "aws-amplify": ["AWS Amplify"],
    "aws-application-migration-service": ["AWS Application Migration Service", "Application Migration Service"],
    "aws-application-discovery-service": ["AWS Application Discovery Service"],
    "aws-mainframe-modernization": ["AWS Mainframe Modernization"],
    "aws-transform": ["AWS Transform"],
    "amazon-bedrock-agent-core": ["Amazon Bedrock AgentCore", "Bedrock AgentCore"],
    "amazon-bedrock": ["Amazon Bedrock"],
    "amazon-sage-maker-ai": ["Amazon SageMaker AI", "SageMaker AI"],
    "amazon-sage-maker": ["Amazon SageMaker", "SageMaker"],
    "amazon-q": ["Amazon Q Developer", "Amazon Q"],
    "amazon-rekognition": ["Amazon Rekognition", "Rekognition"],
    "amazon-comprehend": ["Amazon Comprehend"],
    "amazon-textract": ["Amazon Textract"],
    "amazon-polly": ["Amazon Polly"],
    "amazon-transcribe": ["Amazon Transcribe"],
    "amazon-translate": ["Amazon Translate"],
    "amazon-lex": ["Amazon Lex"],
    "amazon-connect": ["Amazon Connect"],
    "amazon-pinpoint": ["Amazon Pinpoint"],
    "aws-iot-core": ["AWS IoT Core", "IoT Core"],
    "aws-iot-greengrass": ["AWS IoT Greengrass", "IoT Greengrass"],
    "aws-iot-device-defender": ["AWS IoT Device Defender"],
    "aws-iot-device-management": ["AWS IoT Device Management"],
    "aws-iot-site-wise": ["AWS IoT SiteWise", "IoT SiteWise"],
    "aws-iot-events": ["AWS IoT Events"],
    "aws-iot-twin-maker": ["AWS IoT TwinMaker"],
    "aws-iot-fleet-wise": ["AWS IoT FleetWise"],
    "amazon-work-spaces": ["Amazon WorkSpaces", "WorkSpaces"],
    "aws-device-farm": ["AWS Device Farm", "Device Farm"],
    "aws-serverless-application-repository": ["AWS Serverless Application Repository", "Serverless Application Repository"],
    "aws-marketplace": ["AWS Marketplace"],
    "aws-support": ["AWS Support", "AWS Enterprise Support"],
    "aws-re-post": ["AWS re:Post"],
}

TAG_RE = re.compile(r"<!--.*?-->|<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>", re.S)
TAG_NAME_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)")
HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.S)
TABLE_RE = re.compile(r"<table\b.*?</table>", re.S)
ROW_RE = re.compile(r"(<tr\b[^>]*>)(\s*<(td|th)\b[^>]*>(.*?)</\3>)", re.S)
SKIP_TAGS = {"code", "pre", "a", "kbd", "script", "style", "svg", "textarea", "button"}
DEFINITION = "Definition"

_name_re = None
_name_to_icon = {}


def on_config(config):
    global _name_re
    folder = Path(config["docs_dir"]) / ICON_DIR
    _name_to_icon.clear()
    for stem, names in SERVICES.items():
        if not (folder / f"{stem}.svg").exists():
            log.warning("aws_service_icons: missing icon %s%s.svg; skipped", ICON_DIR, stem)
            continue
        for name in names:
            _name_to_icon[name] = stem
    alternatives = sorted(_name_to_icon, key=len, reverse=True)
    _name_re = re.compile(
        r"(?<![\w\-/.@])(" + "|".join(re.escape(n) for n in alternatives) + r")(?![\w\-@])"
    )
    return config


def _icon(stem, prefix, cls):
    return (
        f'<img class="{cls} off-glb" src="{prefix}{ICON_DIR}{stem}.svg" '
        f'alt="" aria-hidden="true" loading="lazy">'
    )


def _plain(html):
    return re.sub(r"<[^>]+>", "", html).strip()


def _leading_service(cell_html):
    """Icon stem of the service a table cell starts with, or None."""
    m = _name_re.match(_plain(cell_html))
    return _name_to_icon[m.group(1)] if m else None


def _decorate_heading(inner, prefix):
    """Insert an icon before each distinct service named in a heading."""
    seen = set()
    out, pos, skip = [], 0, 0

    def repl(m):
        stem = _name_to_icon[m.group(1)]
        if stem in seen:
            return m.group(0)
        seen.add(stem)
        first, sep, rest = m.group(1).partition(" ")
        # Keep the icon on the same line as the first word of the name.
        return f'<span class="aws-svc">{_icon(stem, prefix, "aws-svc-icon")}{first}</span>{sep}{rest}'

    for m in TAG_RE.finditer(inner):
        text = inner[pos:m.start()]
        out.append(_name_re.sub(repl, text) if skip == 0 else text)
        out.append(m.group(0))
        pos = m.end()
        t = TAG_NAME_RE.match(m.group(0))
        if t and t.group(2).lower() in SKIP_TAGS and not m.group(0).endswith("/>"):
            skip = max(0, skip - 1) if t.group(1) else skip + 1
    out.append(_name_re.sub(repl, inner[pos:]) if skip == 0 else inner[pos:])
    return "".join(out)


def _add_icon_column(table, prefix):
    rows = list(ROW_RE.finditer(table))
    body = [r for r in rows if r.group(3) == "td"]
    stems = [_leading_service(r.group(4)) for r in body]
    if not body or sum(1 for s in stems if s) * 2 < len(body):
        return table

    def repl(m):
        if m.group(3) == "th":
            cell = '<th class="aws-svc-col"></th>'
        else:
            stem = _leading_service(m.group(4))
            cell = f'<td class="aws-svc-col">{_icon(stem, prefix, "aws-svc-col-icon") if stem else ""}</td>'
        return m.group(1) + cell + m.group(2)

    return ROW_RE.sub(repl, table)


def _definition_spans(html):
    """(start, end) offsets of each Definition section's body."""
    spans, open_at, open_level = [], None, None
    for m in HEADING_RE.finditer(html):
        level = int(m.group(1))
        if open_at is not None and level <= open_level:
            spans.append((open_at, m.start()))
            open_at = None
        if open_at is None and _plain(m.group(2)).rstrip("¶").strip() == DEFINITION:
            open_at, open_level = m.end(), level
    if open_at is not None:
        spans.append((open_at, len(html)))
    return spans


def on_page_content(html, page, config, files):
    if _name_re is None or not page.file.src_uri.startswith("unit"):
        return html
    prefix = "../" * page.url.count("/")

    # 1. Icon column in Definition tables (work backwards so offsets hold).
    for start, end in reversed(_definition_spans(html)):
        section = TABLE_RE.sub(lambda m: _add_icon_column(m.group(0), prefix), html[start:end])
        html = html[:start] + section + html[end:]

    # 2. Icons in section headings (not the page title).
    def heading(m):
        if m.group(1) == "1":
            return m.group(0)
        open_tag_end = m.group(0).index(">") + 1
        return (
            m.group(0)[:open_tag_end]
            + _decorate_heading(m.group(2), prefix)
            + f"</h{m.group(1)}>"
        )

    return HEADING_RE.sub(heading, html)
