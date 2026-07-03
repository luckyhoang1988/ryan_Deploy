# Claude Integration Guide - RyanDeploy

**Hướng dẫn sử dụng Claude API và Claude Code cho dự án RyanDeploy**

---

## 📋 **Mục Lục**

1. [Setup Claude API](#setup-claude-api)
2. [Claude Code Setup](#claude-code-setup)
3. [Integration Points](#integration-points)
4. [Prompt Engineering](#prompt-engineering)
5. [Best Practices](#best-practices)
6. [Troubleshooting](#troubleshooting)

---

## 🔑 **Setup Claude API**

### **1. Lấy API Key**

```bash
# Vào: https://console.anthropic.com/account/api-keys
# Tạo new API key
# Format: sk-ant-v4-xxxxxxxxxxxxx

# Lưu vào .env file
export ANTHROPIC_API_KEY="sk-ant-v4-xxxxxxxxxxxxx"
```

### **2. Install Library**

```bash
# Thêm vào requirements.txt
pip install anthropic

# Hoặc cài riêng
pip install anthropic --break-system-packages
```

### **3. Basic Usage**

```python
# backend/apps/integrations/claude_api.py

from anthropic import Anthropic
import os

class ClaudeAnalyzer:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-opus-4-6"
    
    def analyze_deployment(self, deployment_data: dict) -> dict:
        """
        Analyze deployment for risks and recommendations
        
        Args:
            deployment_data: {
                'package': 'Microsoft Office',
                'target_machines': ['PC-01', 'PC-02'],
                'system_requirements': {...},
                'available_licenses': 100,
                'machines_info': [...]
            }
        
        Returns:
            {
                'feasibility': 'yes/no',
                'risk_score': 0.0-1.0,
                'risks': [...],
                'recommendations': [...],
                'estimated_duration': 30
            }
        """
        
        prompt = self._build_analysis_prompt(deployment_data)
        
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return self._parse_response(message.content[0].text)
    
    def _build_analysis_prompt(self, data: dict) -> str:
        return f"""
Bạn là IT deployment expert. Phân tích yêu cầu deployment này:

**PACKAGE:**
- Tên: {data.get('package')}
- Yêu cầu: {data.get('system_requirements')}
- License khả dụng: {data.get('available_licenses')}

**TARGET MACHINES:**
{self._format_machines(data.get('machines_info', []))}

Trả lời dưới dạng JSON:
{{
    "feasibility": "yes/no",
    "risk_score": 0.0-1.0,
    "risks": ["risk1", "risk2"],
    "recommendations": ["rec1", "rec2"],
    "estimated_duration_minutes": 30
}}
"""
    
    def _format_machines(self, machines: list) -> str:
        return "\n".join([
            f"- {m['hostname']}: {m['os']}, RAM: {m['ram_gb']}GB, Disk: {m['disk_gb']}GB"
            for m in machines
        ])
    
    def _parse_response(self, response_text: str) -> dict:
        import json
        import re
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        return {
            "feasibility": "unknown",
            "risk_score": 0.5,
            "risks": ["Failed to parse response"],
            "recommendations": []
        }
```

---

## 💻 **Claude Code Setup**

### **1. Install Claude Code Extension**

```bash
# VSCode
# 1. Open Extensions (Ctrl+Shift+X)
# 2. Search "Claude Code"
# 3. Install Anthropic's official extension

# Or via command line
code --install-extension Anthropic.claude
```

### **2. Configure in VSCode**

```json
// .vscode/settings.json
{
  "anthropic.apiKey": "${env:ANTHROPIC_API_KEY}",
  "anthropic.model": "claude-opus-4-6",
  "anthropic.temperature": 0.2,
  "anthropic.maxTokens": 2048
}
```

### **3. Using Claude Code for Development**

```bash
# Mở command palette: Ctrl+Shift+P
# Type: "Claude: Start Session"

# Hoặc tạo new file và type:
# @claude generate [description]

# Ví dụ:
# @claude generate database model for package management
# @claude generate api endpoint for deployment
# @claude generate test cases for executor
```

---

## 🔗 **Integration Points**

### **1. Pre-Deployment Analysis** ✅

**File:** `backend/apps/deployments/views.py`

```python
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Deployment
from apps.integrations.claude_api import ClaudeAnalyzer

@api_view(['POST'])
def analyze_deployment(request):
    """
    POST /api/deployments/analyze/
    
    Body: {
        "package_id": 1,
        "target_pc_ids": [1, 2, 3],
        "user_count": 3
    }
    """
    
    deployment_id = request.data.get('deployment_id')
    deployment = Deployment.objects.get(id=deployment_id)
    
    # Prepare data for Claude
    data = {
        'package': deployment.package_version.package.name,
        'system_requirements': {
            'os': deployment.package_version.package.min_os,
            'ram_gb': deployment.package_version.package.min_ram_gb,
            'disk_gb': deployment.package_version.package.min_disk_gb,
        },
        'available_licenses': deployment.package_version.package.available_licenses,
        'machines_info': [
            {
                'hostname': m.hostname,
                'os': m.os_name,
                'ram_gb': m.ram_gb,
                'disk_gb': m.available_disk_gb
            }
            for m in deployment.target_machines.all()
        ]
    }
    
    # Analyze with Claude
    analyzer = ClaudeAnalyzer()
    analysis = analyzer.analyze_deployment(data)
    
    # Save analysis
    deployment.ai_analysis = analysis
    deployment.feasibility_score = 1.0 - analysis['risk_score']
    deployment.save()
    
    return Response(analysis)
```

### **2. Smart Recommendations** ✅

**File:** `backend/apps/integrations/claude_api.py`

```python
def get_recommendations(self, deployment_id: int) -> list:
    """Get smart recommendations from Claude"""
    
    deployment = Deployment.objects.get(id=deployment_id)
    
    # Historical data
    similar_deployments = Deployment.objects.filter(
        package=deployment.package
    ).exclude(status__in=['failed', 'rejected'])
    
    prompt = f"""
Dựa vào lịch sử deployment này, cho các khuyến cáo tối ưu:

Deployment hiện tại:
- Package: {deployment.package_version.package.name}
- Machines: {deployment.target_machines.count()}
- Scheduled: {deployment.scheduled_datetime}

Lịch sử (3 deployment gần nhất):
{self._format_history(similar_deployments[:3])}

Khuyến cáo (JSON):
{{
    "optimal_time": "22:00-06:00",
    "max_parallel": 10,
    "pre_checks": ["check1", "check2"],
    "rollback_strategy": "..."
}}
"""
    
    message = self.client.messages.create(
        model=self.model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return self._parse_response(message.content[0].text)
```

### **3. Error Analysis & Troubleshooting** ✅

**File:** `backend/apps/integrations/claude_api.py`

```python
def analyze_failure(self, job_id: int) -> dict:
    """
    Analyze job failure and suggest fixes
    """
    from apps.jobs.models import Job
    
    job = Job.objects.get(id=job_id)
    
    prompt = f"""
Phân tích lỗi deployment này:

Package: {job.deployment.package_version.package.name}
Machine: {job.machine.hostname}
OS: {job.machine.os_name}

Error Message:
{job.error_output}

Output Log:
{job.output[-1000:]}  # Last 1000 chars

Phân tích và đề xuất cách fix:
{{
    "root_cause": "...",
    "severity": "critical/high/medium/low",
    "solutions": ["solution1", "solution2"],
    "retry_recommended": true/false
}}
"""
    
    message = self.client.messages.create(
        model=self.model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return self._parse_response(message.content[0].text)
```

### **4. Generate Reports** ✅

**File:** `backend/apps/reports/generators.py`

```python
from apps.integrations.claude_api import ClaudeAnalyzer

def generate_deployment_summary(deployment_id: int) -> str:
    """Generate executive summary using Claude"""
    
    from apps.deployments.models import Deployment
    
    deployment = Deployment.objects.get(id=deployment_id)
    logs = deployment.jobs.all()
    
    prompt = f"""
Viết executive summary cho deployment này (tiếng Việt):

Package: {deployment.package_version.package.name}
Target: {deployment.target_machines.count()} machines
Duration: {deployment.completed_at - deployment.started_at}

Results:
- Success: {deployment.success_count}/{deployment.target_machines.count()}
- Failed: {deployment.failed_count}
- Issues: [list of errors]

Viết summary 5-10 dòng, chuyên nghiệp, để send cho manager.
"""
    
    analyzer = ClaudeAnalyzer()
    message = analyzer.client.messages.create(
        model=analyzer.model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return message.content[0].text
```

---

## 🎯 **Prompt Engineering**

### **Best Prompts for RyanDeploy**

#### **1. Deployment Feasibility**

```python
prompt = """
Bạn là IT deployment expert có 10 năm kinh nghiệm.
Phân tích deployment request này:

[PACKAGE INFO]
[MACHINE INFO]
[LICENSE INFO]

Đánh giá:
1. Khả năng thành công (%)
2. Rủi ro chính
3. Khuyến cáo
4. Thời gian ước tính

Format: JSON
"""
```

#### **2. Error Root Cause**

```python
prompt = """
Bạn là Windows troubleshooting expert.
Phân tích error log này và tìm root cause:

[ERROR LOG]
[SYSTEM INFO]

Trả lời:
1. Nguyên nhân
2. Mức độ nghiêm trọng
3. Cách fix
4. Cách tránh lần sau
"""
```

#### **3. Performance Optimization**

```python
prompt = """
Bạn là deployment performance engineer.
Cho gợi ý tối ưu cho kịch bản này:

[CURRENT STATS]
- Deployment time: 3h for 100 machines
- Success rate: 92%
- Common errors: [...]

Khuyến cáo để cải thiện:
1. Thời gian
2. Success rate
3. Resource usage
"""
```

#### **4. Security Review**

```python
prompt = """
Bạn là security architect.
Review deployment process này cho security risks:

[DEPLOYMENT PROCESS]
[CREDENTIAL HANDLING]
[AUDIT LOG CONFIG]

Identify:
1. Security gaps
2. Risk level
3. Remediation steps
"""
```

### **Prompt Tuning Tips**

```python
# ❌ BAD
prompt = "Deploy software"

# ✅ GOOD
prompt = """
Bạn là IT deployment expert.
Phân tích yêu cầu deployment:
- Package: Microsoft Office 2024
- Machines: 50 máy Windows 10/11
- Requirements: 8GB RAM, 15GB disk
- Timeline: Deploy trong 2 giờ

Đánh giá khả năng thành công và rủi ro.
"""

# Key improvements:
# 1. Định rõ role (IT deployment expert)
# 2. Cung cấp context cụ thể
# 3. Chỉ rõ format output
# 4. Đặt ràng buộc (timeline, requirements)
```

---

## 📚 **Best Practices**

### **1. Caching Responses**

```python
# backend/apps/integrations/claude_api.py

from django.core.cache import cache

def analyze_deployment(self, deployment_id: int) -> dict:
    """Cache analysis results"""
    
    cache_key = f"deployment_analysis_{deployment_id}"
    cached = cache.get(cache_key)
    
    if cached:
        return cached
    
    # Call Claude
    result = self._call_claude(deployment_id)
    
    # Cache for 24 hours
    cache.set(cache_key, result, 86400)
    
    return result
```

### **2. Rate Limiting**

```python
# backend/apps/integrations/claude_api.py

from django.http import HttpResponse
from django.utils.decorators import rate_limit

@rate_limit(rate='100/h')  # 100 calls per hour
def analyze_deployment(request):
    """Rate limited API endpoint"""
    pass
```

### **3. Error Handling**

```python
def analyze_deployment(self, deployment_id: int) -> dict:
    """Robust error handling"""
    
    try:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return self._parse_response(message.content[0].text)
    
    except Exception as e:
        # Log error
        logger.error(f"Claude API error: {e}")
        
        # Return fallback
        return {
            "feasibility": "unknown",
            "risk_score": 0.5,
            "error": str(e),
            "recommendations": ["Contact support"]
        }
```

### **4. Async Processing**

```python
# backend/apps/deployments/tasks.py

from celery import shared_task
from apps.integrations.claude_api import ClaudeAnalyzer

@shared_task
def analyze_deployment_async(deployment_id: int):
    """Async Claude analysis"""
    
    analyzer = ClaudeAnalyzer()
    analysis = analyzer.analyze_deployment(deployment_id)
    
    # Update deployment with analysis
    from apps.deployments.models import Deployment
    deployment = Deployment.objects.get(id=deployment_id)
    deployment.ai_analysis = analysis
    deployment.save()
    
    return analysis
```

### **5. Cost Optimization**

```python
# Use cheaper models when possible
class ClaudeAnalyzer:
    def __init__(self, use_sonnet=False):
        # Use Sonnet 4 for cost savings (cheaper than Opus)
        self.model = "claude-sonnet-4-6" if use_sonnet else "claude-opus-4-6"

# Example usage:
# Simple analysis → use Sonnet (faster, cheaper)
analyzer_simple = ClaudeAnalyzer(use_sonnet=True)

# Complex analysis → use Opus (better quality)
analyzer_complex = ClaudeAnalyzer(use_sonnet=False)
```

---

## 🐛 **Troubleshooting**

### **Problem 1: API Key Not Found**

```bash
# Check env variable
echo $ANTHROPIC_API_KEY

# Set it
export ANTHROPIC_API_KEY="sk-ant-v4-xxxxx"

# Or in Django settings
import os
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
```

### **Problem 2: Rate Limit Exceeded**

```python
import time
from anthropic import RateLimitError

def analyze_with_retry(self, data: dict, max_retries=3):
    for attempt in range(max_retries):
        try:
            return self.analyze_deployment(data)
        except RateLimitError:
            wait_time = 2 ** attempt  # Exponential backoff
            print(f"Rate limited. Waiting {wait_time}s...")
            time.sleep(wait_time)
    
    raise Exception("Max retries exceeded")
```

### **Problem 3: Invalid JSON Response**

```python
def _parse_response(self, response_text: str) -> dict:
    """Robust JSON parsing"""
    
    import json
    import re
    
    try:
        # Try direct parse
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Try extract JSON from text
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
    
    # Return safe default
    return {
        "feasibility": "unknown",
        "risk_score": 0.5,
        "error": "Failed to parse response"
    }
```

### **Problem 4: Timeout**

```python
def analyze_deployment(self, deployment_id: int, timeout=30) -> dict:
    """Set timeout for API calls"""
    
    import asyncio
    
    try:
        message = asyncio.wait_for(
            self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[...]
            ),
            timeout=timeout
        )
        return self._parse_response(message.content[0].text)
    except asyncio.TimeoutError:
        logger.error(f"Claude API timeout after {timeout}s")
        return {"error": "API timeout"}
```

---

## 📝 **Configuration Files**

### **1. Django Settings**

```python
# backend/ryandeploy/settings.py

import os

# Claude API
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-opus-4-6')
CLAUDE_MAX_TOKENS = 1024

# Cache config
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

### **2. Environment Variables**

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-v4-xxxxxxxxxxxxx
CLAUDE_MODEL=claude-opus-4-6
CLAUDE_MAX_TOKENS=2048

# Optional
CLAUDE_CACHE_ENABLED=true
CLAUDE_RATE_LIMIT=100/hour
```

### **3. .github/workflows for Claude**

```yaml
# .github/workflows/claude-generation.yml
name: Generate Code with Claude

on: [pull_request]

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Generate code with Claude
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python scripts/generate_models.py
          python scripts/generate_api.py
```

---

## 🎓 **Learning Resources**

### **Official Documentation**
- Claude API: https://docs.anthropic.com
- Claude Code: https://docs.anthropic.com/en/docs/build-with-claude/code

### **Tutorial**
```python
# Simple example to get started
from anthropic import Anthropic

client = Anthropic()
message = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Xin chào! Bạn là ai?"}
    ]
)

print(message.content[0].text)
# Output: Xin chào! Tôi là Claude, một trợ lý AI...
```

---

## ✅ **Checklist**

Trước khi deploy, đảm bảo:

```
□ API key được set trong environment
□ anthropic library installed
□ Claude integration tests passing
□ Error handling implemented
□ Rate limiting configured
□ Caching enabled
□ Cost monitoring setup
□ Logging configured
□ Documentation updated
```

---

## 📞 **Support & Contact**

```
Lỗi Claude API: https://console.anthropic.com/status
Documentation: https://docs.anthropic.com
Community: https://discourse.anthropic.com

Bạn có thể hỏi Claude trực tiếp!
Prompt: "Giúp tôi debug lỗi này: [error message]"
```

---

**Prepared for:** RyanDeploy Project
**Last Updated:** 2024-03-15
**Version:** 1.0

