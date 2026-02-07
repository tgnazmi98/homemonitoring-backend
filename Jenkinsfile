pipeline {
    agent any

    triggers {
        pollSCM('H/30 * * * *')
    }

    environment {
        COMPOSE_FILE = '/home/tgnazmi/docker-container/docker-compose.yml'
        REPO_DIR     = '/home/tgnazmi/docker-container/repos/backend'
    }

    stages {
        stage('Pull Latest') {
            steps {
                sh "git -C ${REPO_DIR} pull origin main"
            }
        }

        stage('Build Backend') {
            steps {
                sh "docker compose -f ${COMPOSE_FILE} build backend"
            }
        }

        stage('Build Logger') {
            steps {
                sh "docker compose -f ${COMPOSE_FILE} build logger"
            }
        }

        stage('Deploy Backend') {
            steps {
                sh "docker compose -f ${COMPOSE_FILE} up -d --no-deps backend"
            }
        }

        stage('Wait for Backend Health') {
            steps {
                retry(10) {
                    sleep 15
                    sh """
                        CONTAINER_ID=\$(docker compose -f ${COMPOSE_FILE} ps -q backend)
                        STATUS=\$(docker inspect --format='{{.State.Health.Status}}' "\$CONTAINER_ID")
                        echo "Backend health status: \$STATUS"
                        [ "\$STATUS" = "healthy" ]
                    """
                }
            }
        }

        stage('Deploy Logger') {
            steps {
                sh "docker compose -f ${COMPOSE_FILE} up -d --no-deps logger"
            }
        }
    }

    post {
        failure {
            echo 'Backend/Logger deployment failed!'
        }
        success {
            echo 'Backend and Logger deployed successfully.'
        }
    }
}
