// 1. Setup the UI
function setupSecondBrainUI() {
    const ss = SpreadsheetApp.getActiveSpreadsheet();

    // Define the 4 active workflow buckets and their specific columns
    const tabsToCreate = [
        { name: "Tasks", headers: ["Done", "Date", "Time Due", "Task", "Details", "Action Required"] },
        { name: "Touchpoints", headers: ["Done", "Date", "Time Due", "Person", "Context", "Drafted SMS"] },
        { name: "Recon", headers: ["Done", "Date", "Time Due", "Opportunity", "Location", "Next Steps"] },
        { name: "Personal", headers: ["Done", "Date", "Time Due", "Item", "Details", "Notes"] }
    ];

    // 1. Loop through and build the 4 active tabs
    tabsToCreate.forEach(tabInfo => {
        let sheet = ss.getSheetByName(tabInfo.name);
        if (!sheet) {
            sheet = ss.insertSheet(tabInfo.name);
        } else {
            sheet.clear(); // Wipe it clean if it already exists
        }

        // Insert Headers
        sheet.appendRow(tabInfo.headers);
        const headerRange = sheet.getRange(1, 1, 1, tabInfo.headers.length);
        headerRange.setFontWeight("bold")
            .setBackground("#202124") // Dark mode grey header
            .setFontColor("#ffffff")
            .setFontFamily("Montserrat"); // Clean, modern UI font

        // Freeze Top Row & Hide Excel Gridlines
        sheet.setFrozenRows(1);
        sheet.setHiddenGridlines(true);

        // Format the rest of the sheet (Font, alignment, text wrapping)
        const bodyRange = sheet.getRange(2, 1, 999, tabInfo.headers.length);
        bodyRange.setFontFamily("Montserrat").setVerticalAlignment("middle");
        sheet.getRange(2, 2, 999, tabInfo.headers.length - 1).setWrap(true);

        // Insert Checkboxes into Column A
        const checkboxRange = sheet.getRange(2, 1, 999, 1);
        checkboxRange.insertCheckboxes();

        // Add Conditional Formatting (Strike-through and grey out when checked)
        const rule = SpreadsheetApp.newConditionalFormatRule()
            .whenFormulaSatisfied('=$A2=TRUE')
            .setStrikethrough(true)
            .setFontColor('#BDBDBD') // Light grey
            .setRanges([bodyRange])
            .build();

        const rules = sheet.getConditionalFormatRules();
        rules.push(rule);
        sheet.setConditionalFormatRules(rules);

        // Resize Columns to feel like an app dashboard
        sheet.setColumnWidth(1, 50);  // Checkbox
        sheet.setColumnWidth(2, 100); // Date
        sheet.setColumnWidth(3, 100); // Time Due
        sheet.setColumnWidth(4, 150); // Subject
        sheet.setColumnWidth(5, 350); // Details
        if (tabInfo.headers.length > 5) sheet.setColumnWidth(6, 350); // Action/SMS
    });

    // 2. Create the Master Contacts tab (No checkboxes needed here)
    let contactsSheet = ss.getSheetByName("Contacts");
    if (!contactsSheet) {
        contactsSheet = ss.insertSheet("Contacts");
        contactsSheet.appendRow(["Name", "Phone", "Email", "Context / VIP Status"]);
        contactsSheet.getRange("A1:D1").setFontWeight("bold").setBackground("#333333").setFontColor("#ffffff");
        contactsSheet.setFrozenRows(1);
        contactsSheet.setColumnWidth(1, 150);
        contactsSheet.setColumnWidth(4, 300);
    }

    // 3. Delete the default "Sheet1" to keep things clean
    const sheet1 = ss.getSheetByName("Sheet1");
    if (sheet1 && ss.getSheets().length > 1) {
        ss.deleteSheet(sheet1);
    }
}


// 2. HTTP GET - Returns current state context for Gemini
function doGet(e) {
    try {
        const ss = SpreadsheetApp.getActiveSpreadsheet();
        let state = {};

        // Helper function to dynamically grab active items from a given sheet
        function getUncheckedItems(sheetName) {
            const sheet = ss.getSheetByName(sheetName);
            if (sheet) {
                const lastRow = sheet.getLastRow();
                if (lastRow > 1) {
                    const data = sheet.getRange(2, 1, lastRow - 1, 4).getValues(); // Col A(Done)... D(Name)
                    return data.filter(r => r[0] !== true).map(r => r[3]).filter(Boolean);
                }
            }
            return [];
        }

        // Get active items across all tabs
        state.tasks = getUncheckedItems("Tasks");
        state.touchpoints = getUncheckedItems("Touchpoints");
        state.recon = getUncheckedItems("Recon");
        state.personal = getUncheckedItems("Personal");

        // Get Contacts
        const contactsSheet = ss.getSheetByName("Contacts");
        if (contactsSheet) {
            const lastRow = contactsSheet.getLastRow();
            if (lastRow > 1) {
                const data = contactsSheet.getRange(2, 1, lastRow - 1, 4).getValues(); // Name, Phone, Email, Context
                state.contacts = data.map(r => ({
                    name: r[0],
                    context: r[3]
                }));
            } else {
                state.contacts = [];
            }
        }

        return ContentService.createTextOutput(JSON.stringify(state))
            .setMimeType(ContentService.MimeType.JSON);
    } catch (error) {
        return ContentService.createTextOutput(JSON.stringify({ "status": "error", "message": error.toString() }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}


// 3. HTTP POST - Executes Action Commands (ADD_ROW, CHECK_OFF)
function doPost(e) {
    try {
        var payload = JSON.parse(e.postData.contents);
        var actions = payload.actions || [];
        var ss = SpreadsheetApp.getActiveSpreadsheet();
        var results = [];

        actions.forEach(function (action) {
            var sheet = ss.getSheetByName(action.tab);
            if (!sheet) {
                results.push("Error: Tab '" + action.tab + "' not found.");
                return;
            }

            if (action.action_type === "ADD_ROW") {
                // 1. Insert row above Row 2 (pushes current Row 2 down to Row 3)
                // insertRowBefore(2) copies the formatting of the row below it automatically (checkboxes, conditional formatting).
                sheet.insertRowBefore(2);

                // 2. Clear background just in case, but keep the checkbox formatting
                var newRowRange = sheet.getRange(2, 1, 1, sheet.getMaxColumns());
                newRowRange.setBackground(null);
                newRowRange.setFontWeight("normal");

                // 3. Convert "FALSE" to boolean for the checkbox
                var rowData = action.row_data;
                if (action.tab !== "Contacts" && rowData.length > 0 && rowData[0] === "FALSE") {
                    rowData[0] = false;
                }

                // 4. Write data to row 2
                sheet.getRange(2, 1, 1, rowData.length).setValues([rowData]);

                results.push("Inserted row at top of " + action.tab);
            }

            else if (action.action_type === "CHECK_OFF") {
                var lastRow = sheet.getLastRow();
                if (lastRow > 1) {
                    // Look in Column D (Index 3 in values array) for the item name to match
                    // Items in Tasks/Touchpoints/Recon/Personal are usually in Column D because of Time Due in C
                    var taskNames = sheet.getRange(2, 4, lastRow - 1, 1).getValues();
                    var found = false;

                    for (var i = 0; i < taskNames.length; i++) {
                        if (taskNames[i][0].toString().toLowerCase().includes(action.task_name.toLowerCase())) {
                            // Check off Column A (Offset +2 for data row, 1 for Col A)
                            sheet.getRange(i + 2, 1).setValue(true);
                            found = true;
                            results.push("Checked off '" + action.task_name + "' in " + action.tab);
                            break; // Only check off the first match
                        }
                    }
                    if (!found) {
                        results.push("Could not find '" + action.task_name + "' to check off in " + action.tab);
                    }

                    // Drop the checked item to the bottom of the unchecked list by sorting ascending (FALSE comes before TRUE)
                    sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).sort({ column: 1, ascending: true });
                }
            }
        });

        return ContentService.createTextOutput(JSON.stringify({ "status": "success", "results": results }))
            .setMimeType(ContentService.MimeType.JSON);

    } catch (error) {
        return ContentService.createTextOutput(JSON.stringify({ "status": "error", "message": error.toString() }))
            .setMimeType(ContentService.MimeType.JSON);
    }
}
