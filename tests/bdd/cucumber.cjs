module.exports = {
  default: {
    import: ['dist/support/**/*.js', 'dist/steps/**/*.js'],
    features: ['features/**/*.feature'],
    format: ['progress', 'html:cucumber-report.html'],
    formatOptions: { snippetInterface: 'async-await' },
    timeout: 30000,
    parallel: 1,
    tags: 'not @pending and not @pending-mcp-sdk-behavior'
  },
  all: {
    import: ['dist/support/**/*.js', 'dist/steps/**/*.js'],
    features: ['features/**/*.feature'],
    format: ['progress', 'html:cucumber-report.html'],
    formatOptions: { snippetInterface: 'async-await' },
    timeout: 30000,
    parallel: 1
  }
};
