#!/bin/bash
set -e

# Check if template ID is provided
if [ -z "$1" ]; then
  echo "Error: Template ID is required"
  echo "Usage: $0 <template_id>"
  exit 1
fi

TEMPLATE_ID=$1
README_PATH="official-templates/pytorch/README.md"
API_KEY=$RUNPOD_API_KEY

# Check if API key is set
if [ -z "$API_KEY" ]; then
  echo "Error: RUNPOD_API_KEY environment variable is not set"
  exit 1
fi

# Read README content
if [ ! -f "$README_PATH" ]; then
  echo "Error: README file not found at $README_PATH"
  exit 1
fi

# Use Node.js to escape the README content for JSON
README_JSON=$(node -e "console.log(JSON.stringify(require('fs').readFileSync('$README_PATH', 'utf8')))")

# Create GraphQL query
cat << EOF > query.json
{
  "query": "mutation AdminUpdatePodTemplate(\$input: AdminUpdatePodTemplateInput!) { adminUpdatePodTemplate(input: \$input) { id name } }",
  "variables": {
    "input": {
      "id": "$TEMPLATE_ID",
      "readme": $README_JSON
    }
  }
}
EOF

# Execute GraphQL mutation
echo "Updating template $TEMPLATE_ID..."
response=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d @query.json \
  https://api.runpod.io/graphql)

# Check for errors
if echo "$response" | grep -q "errors"; then
  echo "❌ GraphQL mutation failed for template $TEMPLATE_ID:"
  echo "$response"
  exit 1
else
  echo "✅ GraphQL mutation successful for template $TEMPLATE_ID:"
  echo "$response"
fi

# Clean up
rm query.json 