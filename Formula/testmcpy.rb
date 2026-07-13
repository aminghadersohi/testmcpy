class Testmcpy < Formula
  include Language::Python::Virtualenv

  desc "MCP Testing Framework - Test LLM tool calling with MCP services"
  homepage "https://github.com/preset-io/testmcpy"
  url "https://files.pythonhosted.org/packages/75/cc/5f97a2cacd242bcb89e6a85a6ac76c64c680460919c1b75198654d358a54/testmcpy-0.11.8.tar.gz"
  sha256 "3cc86d1e4d0f0dfa46a4b37f5dce2789dac69c9f9e7ada709313490513f5524d"
  license "Apache-2.0"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "MCP Testing Framework", shell_output("#{bin}/testmcpy --help")
  end
end
