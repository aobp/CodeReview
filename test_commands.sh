#!/bin/bash
# Test commands for Code Review Agent CLI
# This script provides ready-to-run commands for testing the new CLI interface

REPO_PATH="/Users/wangyue/Code/CodeReviewData/ReviewDataset/sentry-greptile"
BASE_BRANCH="performance-optimization-baseline"
HEAD_BRANCH="performance-enhancement-complete"

echo "=========================================="
echo "Code Review Agent - Test Commands"
echo "=========================================="
echo ""

# Command 1: Git branch mode - Compare two branches
echo "Command 1: Git branch mode (comparing branches)"
echo "----------------------------------------"
echo "python main.py --repo $REPO_PATH --base $BASE_BRANCH --head $HEAD_BRANCH"
echo ""

# Command 2: Git branch mode - Compare HEAD with base
echo "Command 2: Git branch mode (HEAD vs base)"
echo "----------------------------------------"
echo "python main.py --repo $REPO_PATH --base $BASE_BRANCH"
echo ""

# Command 3: Generate diff file first, then use it
echo "Command 3: Generate diff file, then use file mode"
echo "----------------------------------------"
echo "# Step 1: Generate diff file"
echo "cd $REPO_PATH"
echo "git checkout $HEAD_BRANCH"
echo "git diff $BASE_BRANCH...$HEAD_BRANCH > /tmp/sentry-greptile.diff"
echo "cd -"
echo ""
echo "# Step 2: Use the diff file"
echo "python main.py --repo $REPO_PATH --diff /tmp/sentry-greptile.diff"
echo ""

# Command 4: With custom output file
echo "Command 4: Git mode with custom output"
echo "----------------------------------------"
echo "python main.py --repo $REPO_PATH --base $BASE_BRANCH --head $HEAD_BRANCH --output review_results.json"
echo ""

echo "=========================================="
echo "Quick Test (uncomment to run):"
echo "=========================================="
echo "# python main.py --repo $REPO_PATH --base $BASE_BRANCH --head $HEAD_BRANCH"
echo ""
