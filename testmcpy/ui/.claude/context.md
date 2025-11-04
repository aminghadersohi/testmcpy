# testmcpy UI - React/Vite Frontend

## Purpose
React-based web interface for the testmcpy MCP testing framework. Built with Vite, React Router, and Tailwind CSS. Provides an interactive UI for exploring MCP servers, testing tools, managing test cases, and chatting with LLMs using MCP tools.

## Architecture Overview

### Tech Stack
- **Framework**: React 18 + Vite
- **Routing**: React Router v6
- **Styling**: Tailwind CSS (custom design system with CSS variables)
- **Code Editor**: Monaco Editor (VS Code's editor)
- **JSON Viewer**: @microlink/react-json-view
- **Icons**: Lucide React

### Build Process
```bash
npm install          # Install dependencies
npm run dev          # Development server (port 5173)
npm run build        # Production build -> dist/
npm run preview      # Preview production build
```

## Key Pages

### 1. App.jsx - Main Application Shell
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/App.jsx`

**Responsibilities**:
- Application layout with sidebar navigation
- MCP profile selection and management
- Global state for selected MCP profiles
- Route configuration

**Key Features**:
- **Sidebar Navigation**: Collapsible sidebar with navigation to all pages
- **MCP Profile Selector**: Widget in sidebar footer to select active MCP server(s)
- **Profile Modal**: Full-screen modal for selecting MCP profiles/servers
- **Local Storage**: Persists selected profiles in `localStorage` with key `selectedMCPProfiles`
- **Single vs Multiple Selection**:
  - Explorer and Chat pages only use the FIRST selected profile (single MCP at a time)
  - Test Manager can work with multiple profiles simultaneously
  - Shows warning banner when multiple are selected but only one is used

**State Management**:
```javascript
selectedProfiles: []  // Array of strings in format "profile_id:mcp_name"
// e.g., ["default:filesystem", "default:github"]
```

**Profile Storage Format**:
```javascript
// In localStorage as 'selectedMCPProfiles'
["profile_id:mcp_name"]  // Array of profile:server identifiers
```

### 2. MCPExplorer.jsx - Tool/Resource/Prompt Browser
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/pages/MCPExplorer.jsx`

**Responsibilities**:
- Browse and explore MCP tools, resources, and prompts
- Generate tests for individual tools or in batch
- Optimize tool documentation using LLM
- View tool schemas and parameters
- Quick actions (try in chat, run tests, etc.)

**Key Features**:
- **Tabbed Interface**: Tools / Resources / Prompts tabs with counts
- **Search**: Real-time fuzzy search across all items (keyboard shortcut: `/`)
- **Tool Actions**:
  - **Generate Tests**: Opens `TestGenerationModal` for AI test generation
  - **Optimize LLM Docs**: Opens `OptimizeDocsModal` for documentation analysis
  - **Try in Chat**: Navigates to chat with pre-filled tool prompt
  - **Run All Tests**: Runs all tests for a tool directly from explorer
- **Batch Mode**: Select multiple tools and generate tests in batch
- **Test Indicators**: Shows test count badge if tests exist for a tool
- **Code Viewer**: `SchemaCodeViewer` component for exporting schemas as code
- **Parameter Display**: Rich `ParameterCard` components showing schema details
- **Keyboard Shortcuts**: `/` (search), `?` (help), `c` (copy), `Esc` (close)

**Important Pattern - Single Profile Only**:
```javascript
// Explorer uses only the first selected profile
const activeProfile = selectedProfiles.length > 0 ? selectedProfiles[0] : null
const hasMultipleSelected = selectedProfiles.length > 1

// Shows warning if multiple profiles selected
{hasMultipleSelected && <WarningBanner />}
```

**API Calls**:
```javascript
GET  /api/mcp/tools?profiles=profile_id:mcp_name       // Get tools
GET  /api/mcp/resources?profiles=profile_id:mcp_name   // Get resources
GET  /api/mcp/prompts?profiles=profile_id:mcp_name     // Get prompts
POST /api/mcp/optimize-docs                             // Optimize documentation
GET  /api/tests                                         // Get test files
POST /api/tests/run-tool/{tool_name}                    // Run all tests for tool
```

### 3. ChatInterface.jsx - Interactive Chat
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/pages/ChatInterface.jsx`

**Responsibilities**:
- Interactive chat with LLM using MCP tools
- Run evaluators on responses
- Create test cases from successful interactions
- Display tool calls and results

**Key Features**:
- **Message History**: Auto-saved to `localStorage` with key `chatHistory`
- **History Management**: Configurable history size (default 10 messages)
- **Tool Prefill**: Supports pre-filling prompts from Explorer via `localStorage.prefillTool`
- **Auto-expanding Textarea**: Grows as user types (max 6 rows)
- **Model Selection**: Provider + Model dropdowns in header
- **Tool Call Display**: Collapsible tool call sections with JSON viewer
- **Eval Actions**:
  - **Run Eval**: Executes evaluators on assistant response
  - **Create Test**: Generates YAML test case from interaction
- **Rich Metadata**: Shows tokens, cost, duration for each message

**Important Pattern - Single Profile Only**:
```javascript
// Chat uses only the first selected profile
const activeProfile = selectedProfiles.length > 0 ? selectedProfiles[0] : null
```

**API Calls**:
```javascript
POST /api/chat                  // Send message with history
POST /api/eval/run              // Run evaluators
POST /api/tests                 // Create test case
GET  /api/models                // Get available models
```

**Test Case Generation**:
- Automatically includes intelligent evaluators based on actual tool calls:
  - `execution_successful` - Always included
  - `was_mcp_tool_called` - If any tool was called
  - `tool_call_count` - If multiple tools called
  - `tool_called_with_parameters` - Validates key parameters (first 3)
  - `final_answer_contains` - Checks response content

### 4. TestManager.jsx - Test Creation and Management
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/pages/TestManager.jsx`

**Responsibilities**:
- Browse test files organized by folders
- Edit test YAML files using Monaco Editor
- Run tests and view results
- Create new test files

**Key Features**:
- **File Browser**: Left sidebar with folders (organized by tool name) and files
- **Monaco Editor**: Full VS Code editor experience with YAML syntax highlighting
- **Edit Mode**: Toggle between read-only and editable
- **Test Execution**: Run tests with selected provider/model
- **Results Panel**: Slides up from bottom showing test results (uses `TestResultPanel`)
- **Visual Status**: `TestStatusIndicator` shows real-time test execution progress
- **Persistence**: Remembers last selected file in `localStorage.selectedTestFile`

**File Organization**:
```
tests/
├── tool_name_1/           # Folder per tool (auto-created)
│   ├── test_1.yaml
│   └── test_2.yaml
├── tool_name_2/
│   └── test_3.yaml
└── manual_test.yaml       # Root-level files also supported
```

**API Calls**:
```javascript
GET    /api/tests                    // List all test files
GET    /api/tests/{path}             // Load specific test file
PUT    /api/tests/{path}             // Save test file
POST   /api/tests                    // Create new test file
DELETE /api/tests/{path}             // Delete test file
POST   /api/tests/run                // Run tests
GET    /api/models                   // Get available models
```

### 5. Configuration.jsx - Settings
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/pages/Configuration.jsx`

**Responsibilities**:
- View and edit application configuration
- Manage API keys and provider settings
- Configure default models

**API Calls**:
```javascript
GET  /api/config                // Get configuration
PUT  /api/config                // Update configuration
```

### 6. MCPProfiles.jsx - Profile Management
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/pages/MCPProfiles.jsx`

**Responsibilities**:
- Display available MCP profiles and servers
- Allow selection of active profiles
- Embedded in App.jsx modal or standalone page

**Selection Pattern**:
```javascript
// Called when profiles are selected/changed
onSelectProfiles(newProfiles)  // Array of "profile_id:mcp_name" strings

// Saves to localStorage
localStorage.setItem('selectedMCPProfiles', JSON.stringify(newProfiles))
```

## Key Components

### OptimizeDocsModal.jsx - LLM Documentation Optimizer (NEW)
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/components/OptimizeDocsModal.jsx`

**Purpose**: AI-powered analysis and optimization of MCP tool descriptions for better LLM understanding.

**Features**:
- **Multi-step UI**: Analyzing → Success/Error
- **Quality Score**: 0-100 score with severity-based styling
- **Issue Detection**: Categorized issues (clarity, completeness, actionability, examples, constraints)
- **Before/After Comparison**: Side-by-side view of current vs optimized descriptions
- **Copy Actions**: Copy optimized description to clipboard
- **Cost Tracking**: Shows LLM cost and duration

**Opened From**: MCPExplorer.jsx when user clicks "Optimize LLM Docs" button

**API Integration**:
```javascript
POST /api/mcp/optimize-docs
{
  tool_name: string,
  description: string,
  input_schema: object,
  provider: string,
  model: string
}
```

### TestResultPanel.jsx - Test Results Display
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/components/TestResultPanel.jsx`

**Purpose**: Rich, collapsible display of individual test results with evaluator details.

**Features**:
- Expandable/collapsible (auto-expands on failure)
- Shows pass/fail status with color coding
- Displays all evaluator results with scores
- Shows tool calls made during test
- Cost and duration metadata

### TestGenerationModal.jsx - AI Test Generation
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/components/TestGenerationModal.jsx**

**Purpose**: Generate test cases using LLM based on tool schema.

**Features**:
- Configuration options (test count, evaluators, etc.)
- Progress indicator
- Creates YAML test files automatically

### SchemaCodeViewer.jsx - Code Export
**Location**: `/Users/amin/github/preset-io/testmcpy/testmcpy/ui/src/components/SchemaCodeViewer.jsx`

**Purpose**: Export tool schemas as code in multiple languages (Python, TypeScript, JSON).

### Other Components
- **ParameterCard.jsx**: Rich parameter display with type badges, validation info
- **TestStatusIndicator.jsx**: Real-time test execution progress bar
- **TypeBadge.jsx**: Colored badges for data types
- **MCPProfileSelector.jsx**: Profile selection UI

## Important Patterns

### 1. MCP Profile Selection
**Single Selection (Explorer, Chat)**:
```javascript
// Only use first profile from array
const activeProfile = selectedProfiles.length > 0 ? selectedProfiles[0] : null

// Warn if multiple selected
const hasMultipleSelected = selectedProfiles.length > 1
```

**Multiple Selection (Tests)**:
```javascript
// Can use all selected profiles
const profiles = selectedProfiles
```

### 2. Adding a New Page
1. Create component in `/src/pages/YourPage.jsx`
2. Add route in `App.jsx`:
   ```javascript
   import YourPage from './pages/YourPage'

   // In navItems array:
   { path: '/your-path', label: 'Your Label', icon: YourIcon }

   // In Routes:
   <Route path="/your-path" element={<YourPage selectedProfiles={selectedProfiles} />} />
   ```

3. Access selected profiles via props:
   ```javascript
   function YourPage({ selectedProfiles = [] }) {
     const activeProfile = selectedProfiles[0]  // If single selection
     // ... your logic
   }
   ```

### 3. Adding a New Modal
1. Create component in `/src/components/YourModal.jsx`
2. Use state in parent to control visibility:
   ```javascript
   const [showYourModal, setShowYourModal] = useState(false)

   // Render conditionally
   {showYourModal && (
     <YourModal
       onClose={() => setShowYourModal(false)}
       // ... other props
     />
   )}
   ```

3. Modal structure:
   ```javascript
   function YourModal({ onClose }) {
     return (
       <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
         <div className="bg-surface border border-border rounded-xl max-w-4xl">
           {/* Header */}
           <div className="p-6 border-b border-border">
             <button onClick={onClose}><X /></button>
           </div>

           {/* Content */}
           <div className="p-6">
             {/* Your content */}
           </div>

           {/* Footer */}
           <div className="p-6 border-t border-border">
             {/* Actions */}
           </div>
         </div>
       </div>
     )
   }
   ```

### 4. API Call Structure
**Standard Pattern**:
```javascript
const fetchData = async () => {
  try {
    const res = await fetch('/api/endpoint', {
      method: 'POST',  // or GET, PUT, DELETE
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ /* data */ })
    })

    if (!res.ok) {
      const error = await res.json()
      throw new Error(error.detail || 'Unknown error')
    }

    const data = await res.json()
    // Handle success
  } catch (error) {
    console.error('Failed:', error)
    // Handle error
  }
}
```

**With Profile Parameter**:
```javascript
// Single profile
const params = new URLSearchParams()
if (activeProfile) {
  params.append('profiles', activeProfile)
}
const res = await fetch(`/api/endpoint?${params.toString()}`)

// Multiple profiles
if (selectedProfiles.length > 0) {
  selectedProfiles.forEach(p => params.append('profiles', p))
}
```

### 5. LocalStorage Keys
- `selectedMCPProfiles`: Array of selected profile:server identifiers
- `chatHistory`: Chat message history
- `selectedTestFile`: Last selected test file path
- `prefillTool`: Temporary storage for pre-filling chat from explorer
- `test_result_{tool_name}`: Last test run results for a tool

## Styling System

### Design Tokens (CSS Variables)
Defined in `/src/index.css`:

**Colors**:
- `--bg-background`: Main background
- `--bg-surface`: Card/panel background
- `--bg-surface-elevated`: Elevated surfaces
- `--text-primary`, `--text-secondary`, `--text-tertiary`: Text hierarchy
- `--color-primary`: Primary brand color
- `--color-success`, `--color-error`, `--color-warning`, `--color-info`: Status colors
- `--border-default`: Border color

**Common Classes**:
```css
.btn                     /* Base button */
.btn-primary             /* Primary button */
.btn-secondary           /* Secondary button */
.input                   /* Text input */
.card                    /* Card container */
.card-hover              /* Card with hover effect */
.tab                     /* Tab button */
.tab-active              /* Active tab */
```

## Backend API Reference

**Base URL**: `http://localhost:8000` (dev) or configured port

### Core Endpoints
- `GET  /api/config` - Get configuration
- `PUT  /api/config` - Update configuration
- `GET  /api/models` - List available LLM models

### MCP Endpoints
- `GET  /api/mcp/profiles` - List MCP profiles
- `GET  /api/mcp/tools?profiles=...` - List tools
- `GET  /api/mcp/resources?profiles=...` - List resources
- `GET  /api/mcp/prompts?profiles=...` - List prompts
- `POST /api/mcp/optimize-docs` - Optimize tool documentation

### Test Endpoints
- `GET    /api/tests` - List test files
- `GET    /api/tests/{path}` - Get test file
- `POST   /api/tests` - Create test file
- `PUT    /api/tests/{path}` - Update test file
- `DELETE /api/tests/{path}` - Delete test file
- `POST   /api/tests/run` - Run test file
- `POST   /api/tests/run-tool/{tool_name}` - Run all tests for a tool

### Chat & Eval Endpoints
- `POST /api/chat` - Send chat message
- `POST /api/eval/run` - Run evaluators

## Development Tips

### Hot Reload
Vite provides instant HMR. Changes to React components reload immediately.

### Debugging
- React DevTools recommended
- Check Network tab for API calls
- Console logs are preserved in production build

### Common Issues
1. **Profile not loading**: Check `localStorage.selectedMCPProfiles` format
2. **API errors**: Ensure backend is running on correct port
3. **Monaco Editor not loading**: Check build output includes Monaco worker files
4. **Styles not applying**: Verify Tailwind classes and CSS variables

### File Structure
```
testmcpy/ui/
├── src/
│   ├── components/        # Reusable components
│   ├── pages/             # Page components (route endpoints)
│   ├── App.jsx            # Main app shell
│   ├── main.jsx           # Entry point
│   └── index.css          # Global styles + Tailwind
├── public/                # Static assets
├── dist/                  # Build output (generated)
├── package.json           # Dependencies
├── vite.config.js         # Vite configuration
└── tailwind.config.js     # Tailwind configuration
```

## Key Dependencies

- **React 18**: Core framework
- **React Router v6**: Client-side routing
- **Vite**: Build tool and dev server
- **Tailwind CSS**: Utility-first styling
- **Monaco Editor**: Code editor (VS Code)
- **Lucide React**: Icon library
- **@microlink/react-json-view**: JSON viewer with syntax highlighting

## Next Steps for Extension

To add new features, consider:
1. **New evaluators**: Add UI for configuring custom evaluators
2. **Test suites**: Group tests into suites for easier management
3. **Batch operations**: Run multiple test files at once
4. **Export/Import**: Export test results or configurations
5. **Dark/Light mode**: Add theme toggle (CSS variables already support it)
6. **Real-time updates**: WebSocket support for live test progress
