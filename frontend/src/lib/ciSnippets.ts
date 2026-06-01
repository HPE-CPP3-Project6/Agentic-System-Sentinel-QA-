// CI/CD integration snippets (req 8) — copyable pipeline config that runs the
// generated Sentinel-QA pytest harness as a gate. Honest scope: these are
// ready-to-adapt templates. The generated `test_sentinel_api_generated.py` is
// committed by the team (or downloaded from the Scripts tab); the snippets wire
// the secrets + run command around it. SENTINEL_BASE_URL / SENTINEL_TEST_BEARER_TOKEN
// must be provided by the CI environment (repo secrets / credentials store).

export type CiProvider = "github" | "jenkins" | "gitlab";

const SCRIPT = "test_sentinel_api_generated.py";

/** GitHub Actions workflow (.github/workflows/sentinel-qa.yml). */
export function githubActionsSnippet(scriptPath = SCRIPT): string {
  return `# .github/workflows/sentinel-qa.yml
name: Sentinel-QA Security Gate

on:
  pull_request:
  workflow_dispatch:

jobs:
  api-security-tests:
    runs-on: ubuntu-latest
    env:
      SENTINEL_BASE_URL: \${{ secrets.SENTINEL_BASE_URL }}
      SENTINEL_TEST_BEARER_TOKEN: \${{ secrets.SENTINEL_TEST_BEARER_TOKEN }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install test deps
        run: pip install pytest requests

      - name: Run Sentinel-QA generated suite
        run: pytest ${scriptPath} -v --junitxml=sentinel-results.xml

      - name: Publish results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: sentinel-qa-results
          path: sentinel-results.xml
`;
}

/** Declarative Jenkins pipeline (Jenkinsfile). */
export function jenkinsSnippet(scriptPath = SCRIPT): string {
  return `// Jenkinsfile
pipeline {
  agent any
  environment {
    SENTINEL_BASE_URL          = credentials('sentinel-base-url')
    SENTINEL_TEST_BEARER_TOKEN = credentials('sentinel-bearer-token')
  }
  stages {
    stage('Setup') {
      steps {
        sh 'python3 -m venv .venv'
        sh '. .venv/bin/activate && pip install pytest requests'
      }
    }
    stage('Sentinel-QA Security Gate') {
      steps {
        sh '. .venv/bin/activate && pytest ${scriptPath} -v --junitxml=sentinel-results.xml'
      }
    }
  }
  post {
    always {
      junit 'sentinel-results.xml'
    }
  }
}
`;
}

/** GitLab CI job (.gitlab-ci.yml). */
export function gitlabSnippet(scriptPath = SCRIPT): string {
  return `# .gitlab-ci.yml
sentinel-qa:
  image: python:3.11
  variables:
    # Define SENTINEL_BASE_URL and SENTINEL_TEST_BEARER_TOKEN as masked CI/CD variables.
    SENTINEL_BASE_URL: "$SENTINEL_BASE_URL"
    SENTINEL_TEST_BEARER_TOKEN: "$SENTINEL_TEST_BEARER_TOKEN"
  script:
    - pip install pytest requests
    - pytest ${scriptPath} -v --junitxml=sentinel-results.xml
  artifacts:
    when: always
    reports:
      junit: sentinel-results.xml
`;
}

export function ciSnippet(provider: CiProvider, scriptPath = SCRIPT): string {
  switch (provider) {
    case "github":
      return githubActionsSnippet(scriptPath);
    case "jenkins":
      return jenkinsSnippet(scriptPath);
    case "gitlab":
      return gitlabSnippet(scriptPath);
  }
}

export const CI_PROVIDERS: { id: CiProvider; label: string; filename: string }[] = [
  { id: "github", label: "GitHub Actions", filename: "sentinel-qa.yml" },
  { id: "jenkins", label: "Jenkins", filename: "Jenkinsfile" },
  { id: "gitlab", label: "GitLab CI", filename: ".gitlab-ci.yml" },
];
