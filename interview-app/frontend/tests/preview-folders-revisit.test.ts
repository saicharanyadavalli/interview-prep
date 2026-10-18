import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, "..");

describe("Bug C: Close Question Preview & Drawer Modal Verification", () => {
  it("ensures questions/page.tsx handles Close Preview and prevents auto-reopen", () => {
    const filePath = path.join(frontendDir, "src", "app", "questions", "page.tsx");
    const content = fs.readFileSync(filePath, "utf-8");

    // Must track isPreviewClosed
    assert.match(content, /const\s+\[isPreviewClosed,\s*setIsPreviewClosed\]\s*=\s*useState/);

    // Must have handleClosePreview that closes and sets isPreviewClosed
    assert.match(
      content,
      /const\s+handleClosePreview\s*=\s*useCallback\(\(\)\s*=>\s*\{[\s\S]*?setSelectedQnum\(null\)[\s\S]*?setIsPreviewClosed\(true\)/
    );

    // Must NOT auto-select when isPreviewClosed is true
    assert.match(content, /!isPreviewClosedRef\.current/);

    // Must have window Escape key listener
    assert.match(content, /window\.addEventListener\(["']keydown["'],\s*handleKeyDown\)/);
    assert.match(content, /e\.key\s*===\s*["']Escape["']/);

    // Header close button must trigger handleClosePreview
    assert.match(content, /onClick=\{handleClosePreview\}[\s\S]*?Close Preview/);
  });

  it("ensures Drawer.tsx handles Escape, backdrop click, close button, and scroll lock cleanup", () => {
    const drawerPath = path.join(frontendDir, "src", "components", "ui", "Drawer.tsx");
    const content = fs.readFileSync(drawerPath, "utf-8");

    // Close button has aria-label and onClick
    assert.match(content, /aria-label=["']Close drawer["']/);
    assert.match(content, /onClick=\{onClose\}/);

    // Backdrop click calls onClose
    assert.match(content, /onClick=\{onClose\}[\s\S]*?aria-hidden=["']true["']/);

    // Escape key handling
    assert.match(content, /e\.key\s*===\s*["']Escape["'][\s\S]*?onClose\(\)/);

    // Body scroll lock and safe cleanup
    assert.match(content, /document\.body\.style\.overflow\s*=\s*["']hidden["']/);
    assert.match(content, /document\.body\.style\.overflow\s*=\s*originalOverflow\s*\|\|\s*["']/);
  });

  it("ensures QuestionDrawer.tsx implements modal drawer with proper close handling", () => {
    const qDrawerPath = path.join(frontendDir, "src", "components", "questions", "QuestionDrawer.tsx");
    const content = fs.readFileSync(qDrawerPath, "utf-8");

    // Must pass isOpen and onClose to Drawer
    assert.match(content, /<Drawer[^>]*isOpen=\{Boolean\(qnum\)\}[^>]*onClose=\{onClose\}/);
  });
});

describe("Bug I: Custom Question Folders Feature", () => {
  it("ensures CustomFolderModal component exists with required interactive features", () => {
    const modalPath = path.join(frontendDir, "src", "components", "questions", "CustomFolderModal.tsx");
    assert.ok(fs.existsSync(modalPath), "CustomFolderModal.tsx must exist");

    const content = fs.readFileSync(modalPath, "utf-8");

    // Must have Escape key handling
    assert.match(content, /e\.key\s*===\s*["']Escape["']/);

    // Must support creating new folder
    assert.match(content, /Create New Folder/);
    assert.match(content, /Create & Add/);

    // Must indicate when question is already added
    assert.match(content, /Added/);
    assert.match(content, /already/i);
  });

  it("ensures questions/page.tsx replaces alert with CustomFolderModal and persists folders", () => {
    const pagePath = path.join(frontendDir, "src", "app", "questions", "page.tsx");
    const content = fs.readFileSync(pagePath, "utf-8");

    // No primitive alert calls for custom folder
    assert.doesNotMatch(content, /alert\(["'].*custom folder.*["']\)/i);

    // Uses CustomFolderModal
    assert.match(content, /<CustomFolderModal/);
    assert.match(content, /onAddToFolder=\{handleAddToFolder\}/);
    assert.match(content, /onCreateFolderAndAdd=\{handleCreateFolderAndAdd\}/);

    // Has custom folder storage key
    assert.match(content, /questionsCustomFolders_v2/);

    // Displays folder badges in question details
    assert.match(content, /containingFolders/);
  });

  it("ensures API client provides robust Custom Folder endpoints", () => {
    const apiPath = path.join(frontendDir, "src", "lib", "api.ts");
    const content = fs.readFileSync(apiPath, "utf-8");

    assert.match(content, /async\s+getCustomFolders\(\)/);
    assert.match(content, /async\s+createCustomFolder\(/);
    assert.match(content, /async\s+addQuestionToFolder\(/);
    assert.match(content, /async\s+removeQuestionFromFolder\(/);
    assert.match(content, /async\s+deleteCustomFolder\(/);
  });
});

describe("Bug J: Revisit Question Status Toggle & Synchronization", () => {
  it("ensures questions/page.tsx has interactive revisit toggle without primitive alert", () => {
    const pagePath = path.join(frontendDir, "src", "app", "questions", "page.tsx");
    const content = fs.readFileSync(pagePath, "utf-8");

    // No primitive alert calls for revisit
    assert.doesNotMatch(content, /alert\(["'].*revisit.*["']\)/i);

    // Has revisit toggle button text switching
    assert.match(content, /Remove from Revisit Queue/);
    assert.match(content, /Add to Revisit Queue/);

    // Dispatches ipp_revisit_updated event
    assert.match(content, /ipp_revisit_updated/);

    // Calls API.updateProgress
    assert.match(content, /API\.updateProgress\(/);
  });

  it("ensures QuestionDrawer.tsx includes interactive revisit status toggle", () => {
    const qDrawerPath = path.join(frontendDir, "src", "components", "questions", "QuestionDrawer.tsx");
    const content = fs.readFileSync(qDrawerPath, "utf-8");

    // Fetches progress status
    assert.match(content, /API\.getProgressStatus\(/);

    // Toggles revisit
    assert.match(content, /toggleRevisit/);
    assert.match(content, /In Revisit Queue/);
    assert.match(content, /Add to Revisit/);

    // Dispatches ipp_revisit_updated event
    assert.match(content, /ipp_revisit_updated/);
  });

  it("ensures revisit/page.tsx synchronizes with ipp_revisit_updated event immediately", () => {
    const revisitPath = path.join(frontendDir, "src", "app", "revisit", "page.tsx");
    const content = fs.readFileSync(revisitPath, "utf-8");

    assert.match(content, /window\.addEventListener\(["']ipp_revisit_updated["']/);
  });
});
