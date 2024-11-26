#!/bin/bash
set -e

# Remove .git directory to start fresh
rm -rf .git

# Initialize new repository
git init

# Configure git
git config --global user.name "jaydeepraijada"
git config --global user.email "33515393-jraijada25@users.noreply.replit.com"

# Create gitignore to exclude sensitive files
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

# Stage all files except those in gitignore
git add .

# Create commit
git commit -m "Add Healthcare Translation Web App with clean repository"

# Add remote with token using x-access-token format
git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/jaydeepraijada/NaoMedicalTranslateApp.git"

# Push to main branch
git branch -M main
git push -u origin main --force
