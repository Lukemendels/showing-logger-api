function doPost(e) {
    try {
        // Parse the incoming JSON payload
        var data = JSON.parse(e.postData.contents);

        // Get the active sheet
        var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

        // Add headers if the sheet is empty
        if (sheet.getLastRow() === 0) {
            sheet.appendRow([
                "Timestamp",
                "Client Name",
                "Property Address",
                "Sentiment",
                "Action Items",
                "Drafted SMS"
            ]);
            // Optional: Freeze the top row and make it bold
            sheet.getRange(1, 1, 1, 6).setFontWeight("bold");
            sheet.setFrozenRows(1);
        }

        // Add a timestamp as the first column, then the extracted fields
        var row = [
            new Date(),                  // Timestamp
            data.client_name,            // A -> B (with timestamp offset)
            data.property_address,
            data.sentiment,
            data.action_items,
            data.drafted_sms
        ];

        // Append the row to the bottom of the sheet
        sheet.appendRow(row);

        // Return a success response
        return ContentService.createTextOutput(JSON.stringify({ "status": "success" }))
            .setMimeType(ContentService.MimeType.JSON);

    } catch (error) {
        // Return an error response if something goes wrong
        return ContentService.createTextOutput(JSON.stringify({ "status": "error", "message": error.toString() }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}
