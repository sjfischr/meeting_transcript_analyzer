# Script to verify IAM role policies for Lambda functions
# Run this after deployment to confirm Bedrock permissions are correct

Write-Host "Checking IAM Roles for mtg-analyzer Lambda functions..." -ForegroundColor Cyan

# Get all roles for our stack
$roles = aws iam list-roles --query "Roles[?contains(RoleName, 'mtg-analyzer')].RoleName" --output json | ConvertFrom-Json

Write-Host "`nFound $($roles.Count) roles:" -ForegroundColor Green
$roles | ForEach-Object { Write-Host "  - $_" }

# Check PreprocessTurnsFnRole specifically
$preprocessRole = $roles | Where-Object { $_ -like "*PreprocessTurnsFnRole*" }

if ($preprocessRole) {
    Write-Host "`n=== Checking $preprocessRole ===" -ForegroundColor Yellow
    
    # Get inline policies
    Write-Host "`nInline Policies:" -ForegroundColor Cyan
    $policyNames = aws iam list-role-policies --role-name $preprocessRole --output json | ConvertFrom-Json
    
    foreach ($policyName in $policyNames.PolicyNames) {
        Write-Host "  Policy: $policyName" -ForegroundColor White
        $policy = aws iam get-role-policy --role-name $preprocessRole --policy-name $policyName --output json | ConvertFrom-Json
        
        # Check for Bedrock permissions
        $policyDoc = $policy.PolicyDocument | ConvertTo-Json -Depth 10
        if ($policyDoc -match "bedrock:InvokeModel") {
            Write-Host "    ✓ Has bedrock:InvokeModel permission" -ForegroundColor Green
            
            # Extract and display resources
            $statements = $policy.PolicyDocument.Statement
            foreach ($stmt in $statements) {
                if ($stmt.Action -contains "bedrock:InvokeModel") {
                    Write-Host "    Resources:" -ForegroundColor Cyan
                    $stmt.Resource | ForEach-Object { Write-Host "      - $_" -ForegroundColor White }
                }
            }
        } else {
            Write-Host "    ✗ Missing bedrock:InvokeModel permission" -ForegroundColor Red
        }
        
        # Check for S3 permissions
        if ($policyDoc -match "s3:GetObject") {
            Write-Host "    ✓ Has s3:GetObject permission" -ForegroundColor Green
        } else {
            Write-Host "    ✗ Missing s3:GetObject permission" -ForegroundColor Red
        }
    }
} else {
    Write-Host "`n✗ PreprocessTurnsFnRole not found!" -ForegroundColor Red
}

Write-Host "`nDone!" -ForegroundColor Green
