class Testmcpy < Formula
  include Language::Python::Virtualenv

  desc "MCP Testing Framework - Test LLM tool calling with MCP services"
  homepage "https://github.com/preset-io/testmcpy"
  url "https://files.pythonhosted.org/packages/source/t/testmcpy/testmcpy-0.11.0.tar.gz"
  sha256 "ad077f44a99e7b39efc4a9d02493d24daa4e10122b776a9b02bf931050f79f0a"
  license "Apache-2.0"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "MCP Testing Framework", shell_output("#{bin}/testmcpy --help")
  end
end
