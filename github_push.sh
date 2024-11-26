#!/bin/bash
set -e

# Remove existing Git configuration
rm -rf .git

# Initialize new repository
git init

# Configure Git
git config --global user.name "jaydeepraijada"
git config --global user.email "33515393-jraijada25@users.noreply.replit.com"

# Stage files
git add .

# Create initial commit
git commit -m "Initial commit: Healthcare Translation Web App"

# Add remote with token
git remote add origin "https://oauth2:${GITHUB_TOKEN}@github.com/jaydeepraijada/NaoMedicalTranslateApp.git"

# Push to main branch
git branch -M main
git push -u origin main --force
