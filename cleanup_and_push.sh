#!/bin/bash
set -e

# Clean up the repository
rm -rf .git

# Initialize new repository
git init

# Configure Git
git config --global user.name "jaydeepraijada"
git config --global user.email "33515393-jraijada25@users.noreply.replit.com"

# Add files excluding sensitive ones
git add .

# Create commit
git commit -m "Add Healthcare Translation Web App with clean repository"

# Add remote with token using x-access-token format
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/jaydeepraijada/NaoMedicalTranslateApp.git"

# Push to main branch with force
git branch -M main
git push -u origin main --force
