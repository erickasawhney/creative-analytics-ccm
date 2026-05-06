# Google Sheets Feedback Setup Guide (SIMPLE VERSION!)

This setup takes about 3-5 minutes. No service accounts or complicated steps!

## Step 1: Create a Google Sheet (1 minute)
1. Go to [Google Sheets](https://sheets.google.com)
2. Create a new blank spreadsheet 
3. Name it whatever you want (e.g., "Creative Tool Feedback")
4. **Add headers in Row 1:**
   - A1: `timestamp`
   - B1: `satisfaction`
   - C1: `time_spent_with_tool`
   - D1: `time_without_tool`
   - E1: `would_recommend`
   - F1: `user_alias`
   - G1: `comments`
5. **Get the sheet URL** - copy it from your browser (looks like `https://docs.google.com/spreadsheets/d/1234567890abcdef/edit`)

## Step 2: Make Sheet Public for Writing (30 seconds)
1. Click the **Share** button (top right)
2. Click **"Anyone with the link"**
3. Change permission to **"Editor"**
4. Click **Done**

⚠️ **Note:** This makes the sheet publicly editable. If you want more security, you can set it to "Anyone with the link can view" and use a service account instead (more complex setup).

## Step 3: Add Google Sheet URL to Streamlit Cloud (2 minutes)
1. Go to your [Streamlit Cloud Dashboard](https://share.streamlit.io/)
2. Find your app "creative-analytic-ccm"
3. Click the three dots menu (⋮) → **Settings**
4. Go to the **Secrets** section
5. Paste this (replace with YOUR Google Sheet URL):

```toml
[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/YOUR-SHEET-ID/edit"
type = "public"
```

6. Click **Save**

## Step 4: Deploy! (1 minute)
1. Commit and push your code changes to GitHub:
   ```bash
   git add .
   git commit -m "Add Google Sheets feedback integration"
   git push
   ```
2. Streamlit Cloud will automatically redeploy (takes ~1 minute)
3. **Test it!** Submit feedback on your live app
4. Check your Google Sheet - the feedback should appear instantly! 🎉

## View Your Feedback Anytime
Just open your Google Sheet from anywhere to see all feedback submissions in real-time!

## Optional: More Secure Setup
If you want to keep the Google Sheet private (not publicly editable):
1. Create a Google Cloud service account (10 min setup)
2. Share the sheet with the service account email only
3. Add service account credentials to Streamlit secrets

Let me know if you need help with the secure version!

## Troubleshooting
- **Error: "Unable to read spreadsheet"**: Make sure the sheet is shared with "Anyone with the link" and set to "Editor"
- **No data appearing**: Check that Row 1 has the exact column headers listed in Step 1
- **Streamlit not redeploying**: Go to your app dashboard and click "Reboot" to force redeploy
