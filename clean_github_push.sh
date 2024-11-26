#!/bin/bash
set -e

# Clean up any existing git configuration
rm -rf .git

# Initialize new repository
git init

# Configure git
git config --global user.name "jaydeepraijada"
git config --global user.email "33515393-jraijada25@users.noreply.replit.com"

# Ensure .gitignore is up to date
cat > .gitignore << EOL
__pycache__/
*.py[cod]
*$py.class
.env
.venv
env/
venv/
.replit
.upm/
.config/
.cache/
.vercel
*.pyc
.pytest_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.git/
.gitconfig
*.swp
.bash_history
.breakpoints
.replit
replit.nix
.config/
.upm/
.cache/
.env
EOL

# Stage all files
git add .

# Create commit
git commit -m "Healthcare Translation Web App: Complete Implementation"

# Add remote with token using x-access-token format
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/jaydeepraijada/NaoMedicalTranslateApp.git"

# Push to main branch
git branch -M main
git push -u origin main --force
