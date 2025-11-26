pipeline {
    agent {
        docker {
            image 'python:3.10'
            args '-u root:root -v /var/run/docker.sock:/var/run/docker.sock'
        }
    }

    environment {
        DAGSTER_CLOUD_API_TOKEN = credentials('DAGSTER_CLOUD_API_TOKEN')
        ENABLE_FAST_DEPLOYS = 'true'
        PYTHON_VERSION = '3.10'
        DAGSTER_CLOUD_FILE = 'dagster_cloud.yaml'
        DAGSTER_CLOUD_ORGANIZATION = 'izzy-serverless-test'
        DAGSTER_PROJECT_DIR = '.'
    }

    options {
        // Cancel in-progress builds for the same branch
        skipDefaultCheckout(true)
        timeout(time: 30, unit: 'MINUTES')
    }

    //triggers {
        // Trigger builds on SCM changes (equivalent to push events)
    //    pollSCM('H/5 * * * *')
    //}

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Prerun Checks') {
            steps {
                script {
                    // Determine deployment strategy based on branch and PR status
                    env.IS_MAIN_BRANCH = (env.BRANCH_NAME == 'main' || env.BRANCH_NAME == 'master') ? 'true' : 'false'
                    env.IS_PR = env.CHANGE_ID ? 'true' : 'false'

                    // Set deployment strategy (simplified logic)
                    env.DEPLOYMENT_STRATEGY = 'pex-deploy'  // Default to PEX for faster builds

                    echo "Branch: ${env.BRANCH_NAME}"
                    echo "Is Main Branch: ${env.IS_MAIN_BRANCH}"
                    echo "Is PR: ${env.IS_PR}"
                    echo "Deployment Strategy: ${env.DEPLOYMENT_STRATEGY}"
                }
            }
        }

        stage('Setup CLI') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    // Install Dagster Cloud CLI and uv if not already available
                    sh '''
                        if ! command -v dagster-cloud &> /dev/null; then
                            pip install dagster-cloud
                        fi

                        # Install uv for faster dependency management
                        pip install uv
                    '''
                }
            }
        }

        stage('Initialize Build Session') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    // Parse dagster_cloud.yaml and initialize build session
                    def deploymentName = env.IS_MAIN_BRANCH == 'true' ? 'prod' : env.BRANCH_NAME

                    // Get git metadata for Dagster+ UI
                    def gitUrl = scm.userRemoteConfigs[0].url
                    def commitHash = sh(script: 'git rev-parse HEAD', returnStdout: true).trim()

                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        python${PYTHON_VERSION} -m uv run dg plus deploy start \
                            --deployment ${deploymentName} \
                            --git-url ${gitUrl} \
                            --commit-hash ${commitHash} \
                            --yes
                    """
                }
            }
        }

        stage('Refresh Defs State') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    // Refresh state for any StateBackedComponents in the project
                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        python${PYTHON_VERSION} -m uv run dg plus deploy refresh-defs-state
                    """
                }
            }
        }

        stage('Setup Python') {
            when {
                environment name: 'DEPLOYMENT_STRATEGY', value: 'pex-deploy'
            }
            steps {
                script {
                    // Install Python and required packages
                    sh '''
                        # Ensure Python version is available
                        python${PYTHON_VERSION} --version || {
                            echo "Python ${PYTHON_VERSION} not found. Please install it first."
                            exit 1
                        }

                        # Install setuptools
                        python${PYTHON_VERSION} -m pip install setuptools
                    '''
                }
            }
        }

        stage('Build and Push') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    // Build and push code locations to Dagster Cloud
                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        python${PYTHON_VERSION} -m uv run dg plus deploy build-and-push --agent-type=serverless --python-version ${PYTHON_VERSION}
                    """
                }
            }
        }

        stage('Deploy to Dagster Cloud') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        python${PYTHON_VERSION} -m uv run dg plus deploy finish
                    """
                }
            }
        }

        stage('Update PR Comment') {
            when {
                allOf {
                    not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
                    environment name: 'IS_PR', value: 'true'
                }
            }
            steps {
                script {
                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        dagster-cloud ci notify --project-dir=${DAGSTER_PROJECT_DIR}
                    """
                }
            }
        }

        stage('Generate Summary') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    sh """
                        cd ${DAGSTER_PROJECT_DIR}
                        echo "## Dagster Cloud Deployment Summary" > deployment_summary.md
                        dagster-cloud ci status --output-format=markdown >> deployment_summary.md
                    """

                    // Archive the summary for Jenkins UI
                    archiveArtifacts artifacts: 'deployment_summary.md', allowEmptyArchive: true

                    // Display summary in build log
                    sh 'cat deployment_summary.md'
                }
            }
        }
    }

    post {
        always {
            script {
                // Clean up workspace if needed
                cleanWs(cleanWhenAborted: true, cleanWhenFailure: true, cleanWhenSuccess: true)
            }
        }

        success {
            echo 'Dagster Cloud deployment completed successfully!'
        }

        failure {
            echo 'Dagster Cloud deployment failed. Check the logs for details.'
        }

        unstable {
            echo 'Dagster Cloud deployment completed with warnings.'
        }
    }
}