pipeline {
    agent any

    triggers {
        pollSCM('H/2 * * * *')
    }

    environment {
        COMPOSE_FILE = '/home/tgnazmi/docker-container/docker-compose.yml'
        REPO_DIR     = '/home/tgnazmi/docker-container/repos/backend'
    }

    stages {
        stage('Pull Latest') {
            steps {
                dir("${REPO_DIR}") {
                    sh 'git pull origin main'
                }
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
                    sh 'curl -f http://backend:8000/health/ || curl -f http://localhost:8000/health/'
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
