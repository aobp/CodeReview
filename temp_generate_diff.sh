#!/bin/bash
# Temporary script to generate Git diff between two branches for manual review

REPO_PATH="/Users/wangyue/Code/CodeReviewData/ReviewDataset/sentry-greptile"
BASE_BRANCH="performance-optimization-baseline"
HEAD_BRANCH="performance-enhancement-complete"

# Get the script directory (project root) - save it before changing directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_FILE="$SCRIPT_DIR/temp_diff_output.diff"

echo "=========================================="
echo "Generating Git Diff"
echo "=========================================="
echo "Repository: $REPO_PATH"
echo "Base branch: $BASE_BRANCH"
echo "Head branch: $HEAD_BRANCH"
echo "Output file: $OUTPUT_FILE"
echo ""

# Check if repository exists
if [ ! -d "$REPO_PATH" ]; then
    echo "❌ Error: Repository path does not exist: $REPO_PATH"
    exit 1
fi

# Change to repository directory
cd "$REPO_PATH" || exit 1

# Check if it's a git repository
if [ ! -d ".git" ]; then
    echo "❌ Error: Not a Git repository: $REPO_PATH"
    exit 1
fi

# Check if branches exist
if ! git show-ref --verify --quiet refs/heads/"$BASE_BRANCH"; then
    echo "❌ Error: Base branch '$BASE_BRANCH' does not exist"
    exit 1
fi

if ! git show-ref --verify --quiet refs/heads/"$HEAD_BRANCH"; then
    echo "❌ Error: Head branch '$HEAD_BRANCH' does not exist"
    exit 1
fi

# Generate diff using triple-dot syntax (shows changes in head that are not in base)
echo "🔀 Generating diff: $BASE_BRANCH...$HEAD_BRANCH"
echo ""

# Save current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Current branch: $CURRENT_BRANCH"
echo ""

# Generate diff and save to file (absolute path)
echo "Saving diff to: $OUTPUT_FILE"
git diff "$BASE_BRANCH...$HEAD_BRANCH" > "$OUTPUT_FILE" 2>&1

if [ $? -eq 0 ]; then
    DIFF_SIZE=$(wc -l < "$OUTPUT_FILE")
    DIFF_BYTES=$(wc -c < "$OUTPUT_FILE")
    
    echo "✅ Diff generated successfully!"
    echo "   Lines: $DIFF_SIZE"
    echo "   Size: $DIFF_BYTES bytes"
    echo "   File: $OUTPUT_FILE"
    echo ""
    
    # Show summary
    echo "📊 Diff Summary:"
    FILES_CHANGED=$(git diff --name-only "$BASE_BRANCH...$HEAD_BRANCH" | wc -l | tr -d ' ')
    echo "   Files changed: $FILES_CHANGED"
    
    # Get stats (compatible with macOS grep)
    STATS=$(git diff --shortstat "$BASE_BRANCH...$HEAD_BRANCH")
    INSERTIONS=$(echo "$STATS" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' || echo '0')
    DELETIONS=$(echo "$STATS" | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' || echo '0')
    echo "   Insertions: $INSERTIONS"
    echo "   Deletions: $DELETIONS"
    echo ""
    
    # List changed files
    echo "📝 Changed files:"
    git diff --name-only "$BASE_BRANCH...$HEAD_BRANCH" | head -20
    CHANGED_COUNT=$(git diff --name-only "$BASE_BRANCH...$HEAD_BRANCH" | wc -l | tr -d ' ')
    if [ "$CHANGED_COUNT" -gt 20 ]; then
        echo "   ... and $((CHANGED_COUNT - 20)) more files"
    fi
    echo ""
    
    echo "💡 You can now review the diff file: $OUTPUT_FILE"
    echo "   Or use: cat $OUTPUT_FILE | less"
else
    echo "❌ Error: Failed to generate diff"
    exit 1
fi
