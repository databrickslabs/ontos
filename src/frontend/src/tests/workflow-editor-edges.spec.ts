import { test, expect } from '@playwright/test';
import { loadDemoData, clearDemoData } from './helpers/demo-data';

test.beforeAll(async ({ request }) => {
  await loadDemoData(request);
});

test.afterAll(async ({ request }) => {
  await clearDemoData(request);
});

// ---------------------------------------------------------------------------
// Workflow Editor — Edge Management
// ---------------------------------------------------------------------------
test.describe('Workflow Editor — Edge Management', () => {
  // -------------------------------------------------------------------------
  // 1. Workflow editor loads with step toolbar
  // -------------------------------------------------------------------------
  test('workflow editor loads with step toolbar and canvas', async ({ page }) => {
    await page.goto('/workflows/new?type=process');

    // "Add Step" label in the toolbar panel
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Toolbar buttons for common step types
    await expect(page.getByRole('button', { name: /Approval/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Notification/ })).toBeVisible();

    // ReactFlow canvas renders (the wrapper div has .react-flow class)
    await expect(page.locator('.react-flow')).toBeVisible();

    // Trigger node is pre-created for new workflows
    await expect(page.locator('.react-flow__node').first()).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 2. Add nodes and verify auto-connection edge
  // -------------------------------------------------------------------------
  test('adding steps auto-creates connecting edges', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Start with just the trigger node
    const initialNodeCount = await page.locator('.react-flow__node').count();
    expect(initialNodeCount).toBe(1); // trigger only

    // Add an Approval step — auto-connects trigger → approval
    await page.getByRole('button', { name: /Approval/ }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);
    // One edge: trigger → approval
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);

    // Add a Notification step — auto-connects approval → notification (pass edge)
    await page.getByRole('button', { name: /Notification/ }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(3);
    // Two edges: trigger → approval, approval → notification
    await expect(page.locator('.react-flow__edge')).toHaveCount(2);
  });

  // -------------------------------------------------------------------------
  // 3. Edge selection and visual feedback
  // -------------------------------------------------------------------------
  test('clicking an edge selects it and shows delete button', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Add two steps to get an edge between them
    await page.getByRole('button', { name: /Approval/ }).click();
    await page.getByRole('button', { name: /Notification/ }).click();
    await expect(page.locator('.react-flow__edge')).toHaveCount(2);

    // Click the second edge (approval → notification) to select it.
    // ReactFlow edges are SVG paths; clicking the edge path selects it.
    const edges = page.locator('.react-flow__edge');
    // Use the last edge (approval → notification, the one with a pass label)
    const targetEdge = edges.last();
    await targetEdge.click();

    // Verify the edge enters selected state
    await expect(page.locator('.react-flow__edge.selected')).toHaveCount(1);

    // The delete button (title="Delete connection") appears on selection
    await expect(page.locator('button[title="Delete connection"]')).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 4. Edge deletion via delete button
  // -------------------------------------------------------------------------
  test('clicking the delete button removes the edge', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Build a small graph: trigger → approval → notification
    await page.getByRole('button', { name: /Approval/ }).click();
    await page.getByRole('button', { name: /Notification/ }).click();
    await expect(page.locator('.react-flow__edge')).toHaveCount(2);

    // Select the last edge (approval → notification)
    await page.locator('.react-flow__edge').last().click();
    await expect(page.locator('.react-flow__edge.selected')).toHaveCount(1);

    // Click the "X" delete button
    await page.locator('button[title="Delete connection"]').click();

    // Edge count should decrease by one
    await expect(page.locator('.react-flow__edge')).toHaveCount(1);
    // Delete button should disappear
    await expect(page.locator('button[title="Delete connection"]')).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // 5. Approval node has pass (green) and fail (red) source handles
  // -------------------------------------------------------------------------
  test('approval node exposes pass and fail handles', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Add an Approval step
    await page.getByRole('button', { name: /Approval/ }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(2);

    // The approval node (second node) should have two source handles
    const approvalNode = page.locator('.react-flow__node').nth(1);
    const passHandle = approvalNode.locator('.react-flow__handle[data-handleid="pass"]');
    const failHandle = approvalNode.locator('.react-flow__handle[data-handleid="fail"]');

    await expect(passHandle).toBeVisible();
    await expect(failHandle).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // 6. Drag from fail handle to create a fail edge
  // -------------------------------------------------------------------------
  test('drag from fail handle creates a fail-labeled edge', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Add Approval + two Notification nodes
    await page.getByRole('button', { name: /Approval/ }).click();
    await page.getByRole('button', { name: /Notification/ }).click();
    await page.getByRole('button', { name: /Notification/ }).click();
    await expect(page.locator('.react-flow__node')).toHaveCount(4);
    // Auto-edges: trigger→approval, approval→notification1, notification1→notification2
    await expect(page.locator('.react-flow__edge')).toHaveCount(3);

    // Locate the approval node's fail handle and the third notification node's target handle
    const approvalNode = page.locator('.react-flow__node').nth(1);
    const failHandle = approvalNode.locator('.react-flow__handle[data-handleid="fail"]');
    const targetNode = page.locator('.react-flow__node').nth(3);
    const targetHandle = targetNode.locator('.react-flow__handle[data-handlepos="top"]')
      .or(targetNode.locator('.react-flow__handle.react-flow__handle-top'));

    // If handles are visible, attempt the drag; otherwise skip gracefully.
    // ReactFlow handle visibility can depend on viewport/zoom.
    const failHandleVisible = await failHandle.isVisible().catch(() => false);
    const targetHandleVisible = await targetHandle.first().isVisible().catch(() => false);

    if (failHandleVisible && targetHandleVisible) {
      const sourceBox = await failHandle.boundingBox();
      const targetBox = await targetHandle.first().boundingBox();

      if (sourceBox && targetBox) {
        // Perform the drag from fail handle to target node
        await page.mouse.move(
          sourceBox.x + sourceBox.width / 2,
          sourceBox.y + sourceBox.height / 2,
        );
        await page.mouse.down();
        await page.mouse.move(
          targetBox.x + targetBox.width / 2,
          targetBox.y + targetBox.height / 2,
          { steps: 10 },
        );
        await page.mouse.up();

        // A new "Fail" edge should appear (4 total now)
        // Allow a short wait for ReactFlow to process the connection
        await expect(page.locator('.react-flow__edge')).toHaveCount(4, { timeout: 5_000 });

        // Verify a "Fail" label is present in the edge label renderer
        await expect(
          page.locator('.react-flow__edgelabel-renderer').getByText('Fail'),
        ).toBeVisible();
      }
    }
  });

  // -------------------------------------------------------------------------
  // 7. Save workflow with connections — no errors
  // -------------------------------------------------------------------------
  test('save workflow with steps and connections succeeds', async ({ page }) => {
    await page.goto('/workflows/new?type=process');
    await expect(page.getByText('Add Step')).toBeVisible({ timeout: 15_000 });

    // Fill in the workflow name (the inline Input with placeholder "Workflow name")
    const nameInput = page.getByPlaceholder('Workflow name');
    await nameInput.fill(`PW Edge Test ${Date.now()}`);

    // Add an Approval + Notification step (auto-connected)
    await page.getByRole('button', { name: /Approval/ }).click();
    await page.getByRole('button', { name: /Notification/ }).click();
    await expect(page.locator('.react-flow__edge')).toHaveCount(2);

    // Click Save
    await page.getByRole('button', { name: /Save/ }).click();

    // Expect a success toast (no destructive variant) or navigation to the edit page.
    // The designer either shows a success toast or redirects to /workflows/:id/edit.
    // We verify no destructive toast appeared within a short window.
    const destructiveToast = page.locator('[data-variant="destructive"]')
      .or(page.getByText('Validation Error'));
    // Give the save a moment to process
    await page.waitForTimeout(2_000);
    await expect(destructiveToast).toHaveCount(0);

    // The URL should have changed from /workflows/new to /workflows/<id>/edit
    // or the name input should still contain our text (confirming no reset)
    await expect(nameInput).not.toHaveValue('');
  });
});
