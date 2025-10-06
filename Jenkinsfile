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
        DAGSTER_CLOUD_YAML_PATH = '.'
        DAGSTER_CLOUD_FILE = 'dagster_cloud.yaml'
        DAGSTER_CLOUD_ORGANIZATION = 'izzy-serverless-test'
        DAGSTER_CLOUD_URL = 'https://izzy-serverless-test.dagster.cloud'
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

        stage('Validate Configuration') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    // Install Dagster Cloud CLI if not already available
                    sh '''
                        if ! command -v dagster-cloud &> /dev/null; then
                            pip install dagster-cloud
                        fi
                    '''

                    // Validate dagster_cloud.yaml and connection
                    sh '''
                        dagster-cloud ci check \
                            --project-dir ${DAGSTER_CLOUD_YAML_PATH} \
                            --dagster-cloud-yaml-path ${DAGSTER_CLOUD_FILE}
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

                    sh """
                        dagster-cloud ci init \
                            --project-dir ${DAGSTER_CLOUD_YAML_PATH} \
                            --dagster-cloud-yaml-path ${DAGSTER_CLOUD_FILE} \
                            --deployment ${deploymentName} \
                            --statedir /tmp/dagster-cloud-ci
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

        stage('Build PEX') {
            when {
                environment name: 'DEPLOYMENT_STRATEGY', value: 'pex-deploy'
            }
            steps {
                script {
                    sh '''
                        dagster-cloud ci build \
                            --build-strategy=python-executable \
                            --python-version ${PYTHON_VERSION} \
                            --statedir /tmp/dagster-cloud-ci
                    '''
                }
            }
        }

        stage('Build Docker') {
            when {
                environment name: 'DEPLOYMENT_STRATEGY', value: 'docker-deploy'
            }
            steps {
                script {
                    sh '''
                        dagster-cloud ci build \
                            --build-strategy=docker \
                            --python-version ${PYTHON_VERSION} \
                            --statedir /tmp/dagster-cloud-ci
                    '''
                }
            }
        }

        stage('Deploy to Dagster Cloud') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    sh 'dagster-cloud ci deploy --statedir /tmp/dagster-cloud-ci'
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
                    sh '''
                        dagster-cloud ci notify \
                            --project-dir=${DAGSTER_CLOUD_YAML_PATH}
                    '''
                }
            }
        }

        stage('Generate Summary') {
            when {
                not { environment name: 'DEPLOYMENT_STRATEGY', value: 'skip' }
            }
            steps {
                script {
                    sh '''
                        echo "## Dagster Cloud Deployment Summary" > deployment_summary.md
                        dagster-cloud ci status --output-format=markdown --statedir /tmp/dagster-cloud-ci >> deployment_summary.md
                    '''

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