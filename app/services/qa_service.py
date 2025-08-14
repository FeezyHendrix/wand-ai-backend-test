import time
from typing import Dict, List, Optional

import ollama
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.schemas.document import (
    QARequest, QAResponse, CompletenessCheckRequest, 
    CompletenessCheckResponse, SearchRequest
)
from app.services.search_service import SearchService
from app.core.config import get_settings

settings = get_settings()


class QAService:
    """Handles question-answering and completeness checking."""
    
    def __init__(self):
        self.search_service = SearchService()
        self.ollama_client = ollama.Client(host=settings.ollama_base_url)
        self.max_context_length = 4000  # Conservative limit for context
    
    async def answer_question(
        self, 
        db: AsyncSession, 
        qa_request: QARequest
    ) -> QAResponse:
        """Answer a question using the knowledge base."""
        start_time = time.time()
        
        try:
            # Search for relevant context
            search_request = SearchRequest(
                query=qa_request.question,
                limit=qa_request.context_limit,
                similarity_threshold=0.6,
                include_metadata=qa_request.include_sources
            )
            
            search_results = await self.search_service.semantic_search(db, search_request)
            
            if not search_results.results:
                processing_time = (time.time() - start_time) * 1000
                return QAResponse(
                    question=qa_request.question,
                    answer="I couldn't find relevant information in the knowledge base to answer your question.",
                    confidence_score=0.0,
                    sources=[] if qa_request.include_sources else None,
                    completeness_score=0.0,
                    processing_time_ms=round(processing_time, 2)
                )
            
            # Generate answer using Ollama or fallback
            try:
                answer, confidence = await self._generate_answer_with_ollama(
                    qa_request.question, 
                    search_results.results
                )
            except Exception as e:
                logger.warning(f"Ollama unavailable, using fallback: {str(e)}")
                answer, confidence = self._generate_answer_fallback(
                    qa_request.question, 
                    search_results.results
                )
            
            # Calculate completeness score
            completeness_score = self._calculate_completeness_score(
                qa_request.question, 
                search_results.results
            )
            
            processing_time = (time.time() - start_time) * 1000
            
            return QAResponse(
                question=qa_request.question,
                answer=answer,
                confidence_score=confidence,
                sources=search_results.results if qa_request.include_sources else None,
                completeness_score=completeness_score,
                processing_time_ms=round(processing_time, 2)
            )
            
        except Exception as e:
            logger.error(f"Error answering question: {str(e)}")
            raise
    
    async def _generate_answer_with_ollama(
        self, 
        question: str, 
        search_results: List
    ) -> tuple[str, float]:
        """Generate answer using Ollama."""
        try:
            # Prepare context from search results
            context_parts = []
            current_length = 0
            
            for result in search_results:
                content = f"Source: {result.document_filename or 'Unknown'}\n{result.content}\n"
                if current_length + len(content) > self.max_context_length:
                    break
                context_parts.append(content)
                current_length += len(content)
            
            context = "\n---\n".join(context_parts)
            
            # Prepare prompt
            prompt = f"""Based on the following context from the knowledge base, please answer the question accurately and concisely.

Context:
{context}

Question: {question}

Instructions:
- Only use information from the provided context
- If the context doesn't contain enough information, say so clearly
- Be specific and cite relevant details from the context
- Keep your answer concise and focused

Answer:"""

            # Call Ollama API
            response = await self._call_ollama_async(prompt)
            
            answer = response.strip()
            
            # Extract confidence score (simple heuristic)
            confidence = self._estimate_confidence(answer, search_results)
            
            return answer, confidence
            
        except Exception as e:
            logger.error(f"Error generating Ollama answer: {str(e)}")
            raise  # Re-raise to trigger fallback in calling method
    
    async def _call_ollama_async(self, prompt: str) -> str:
        """Call Ollama API asynchronously."""
        import asyncio
        
        def _call_ollama_sync():
            response = self.ollama_client.generate(
                model=settings.ollama_model,
                prompt=prompt,
                options={
                    'temperature': 0.3,
                    'top_p': 0.9,
                    'max_tokens': 500
                }
            )
            return response['response']
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call_ollama_sync)
    
    def _generate_answer_fallback(
        self, 
        question: str, 
        search_results: List
    ) -> tuple[str, float]:
        """Generate answer using simple text processing (fallback)."""
        try:
            if not search_results:
                return "No relevant information found.", 0.0
            
            # Use the most relevant result
            best_result = search_results[0]
            
            # Simple answer generation
            answer = f"Based on the available information: {best_result.content[:300]}..."
            if len(best_result.content) > 300:
                answer += " [Content truncated]"
            
            confidence = min(best_result.similarity_score, 0.8)
            
            return answer, confidence
            
        except Exception as e:
            logger.error(f"Error in fallback answer generation: {str(e)}")
            return "An error occurred while generating the answer.", 0.0
    
    def _estimate_confidence(self, answer: str, search_results: List) -> float:
        """Estimate confidence score for the generated answer."""
        if not search_results:
            return 0.0
        
        #  Heuristic based on:
        # 1. Average similarity score of sources
        # 2. Number of sources
        # 3. Answer length and specificity
        
        avg_similarity = sum(r.similarity_score for r in search_results) / len(search_results)
        source_bonus = min(len(search_results) / 5.0, 0.2)  
        
        # Check if answer indicates uncertainty
        uncertainty_indicators = [
            "i don't know", "unclear", "not enough information", 
            "cannot determine", "insufficient data"
        ]
        
        if any(indicator in answer.lower() for indicator in uncertainty_indicators):
            confidence_penalty = 0.3
        else:
            confidence_penalty = 0.0
        
        confidence = min(avg_similarity + source_bonus - confidence_penalty, 1.0)
        return max(confidence, 0.0)
    
    def _calculate_completeness_score(
        self, 
        question: str, 
        search_results: List
    ) -> float:
        """Calculate how complete the available information is for the question."""
        if not search_results:
            return 0.0
        
        # Heuristic based on:
        # 1. Number of relevant sources
        # 2. Average similarity scores
        # 3. Diversity of sources (different documents)
        
        num_sources = len(search_results)
        avg_similarity = sum(r.similarity_score for r in search_results) / num_sources
        
        # Count unique documents
        unique_docs = len(set(r.document_id for r in search_results))
        diversity_score = min(unique_docs / 3.0, 1.0)  # Normalize to max 3 docs
        
        # Combine scores
        completeness = (
            min(num_sources / 5.0, 0.4) +  # Source count (max 40%)
            avg_similarity * 0.4 +         # Relevance (40%)
            diversity_score * 0.2           # Diversity (20%)
        )
        
        return min(completeness, 1.0)
    
    async def check_completeness(
        self, 
        db: AsyncSession, 
        request: CompletenessCheckRequest
    ) -> CompletenessCheckResponse:
        """Check completeness of knowledge base for a topic."""
        try:
            # Search for information about the topic
            search_request = SearchRequest(
                query=request.topic,
                limit=20,
                similarity_threshold=0.5,
                include_metadata=True
            )
            
            search_results = await self.search_service.semantic_search(db, search_request)
            
            # Analyze coverage
            if request.required_aspects:
                covered_aspects = []
                missing_aspects = []
                
                for aspect in request.required_aspects:
                    aspect_search = SearchRequest(
                        query=f"{request.topic} {aspect}",
                        limit=5,
                        similarity_threshold=0.6
                    )
                    
                    aspect_results = await self.search_service.semantic_search(db, aspect_search)
                    
                    if aspect_results.results:
                        covered_aspects.append(aspect)
                    else:
                        missing_aspects.append(aspect)
                
                completeness_score = len(covered_aspects) / len(request.required_aspects)
                
            else:
                # General completeness assessment
                covered_aspects = self._extract_covered_aspects(search_results.results)
                missing_aspects = self._suggest_missing_aspects(request.topic, covered_aspects)
                
                # Simple scoring based on result count and diversity
                completeness_score = min(len(search_results.results) / 10.0, 1.0)
            
            # Generate recommendations
            recommendations = self._generate_recommendations(
                request.topic, 
                missing_aspects, 
                len(search_results.results)
            )
            
            return CompletenessCheckResponse(
                topic=request.topic,
                completeness_score=round(completeness_score, 2),
                missing_aspects=missing_aspects,
                covered_aspects=covered_aspects,
                recommendations=recommendations
            )
            
        except Exception as e:
            logger.error(f"Error checking completeness: {str(e)}")
            raise
    
    def _extract_covered_aspects(self, search_results: List) -> List[str]:
        """Extract key aspects covered in the search results."""
        # Simple keyword extraction (in production, use more sophisticated NLP)
        aspects = set()
        
        for result in search_results:
            # Extract nouns and key phrases (simplified)
            words = result.content.lower().split()
            for i, word in enumerate(words):
                if len(word) > 3 and word.isalpha():
                    aspects.add(word)
                
                # Look for multi-word concepts
                if i < len(words) - 1:
                    phrase = f"{word} {words[i+1]}"
                    if len(phrase) > 6:
                        aspects.add(phrase)
        
        # Return top aspects (limit to avoid overwhelming response)
        return list(aspects)[:10]
    
    def _suggest_missing_aspects(self, topic: str, covered_aspects: List[str]) -> List[str]:
        """Suggest potentially missing aspects for a topic."""
        # Common aspects for various topics (simplified)
        common_aspects = {
            "default": [
                "definition", "examples", "best practices", "troubleshooting",
                "configuration", "installation", "usage", "limitations"
            ],
            "api": [
                "authentication", "endpoints", "parameters", "responses",
                "rate limiting", "error codes", "examples"
            ],
            "security": [
                "authentication", "authorization", "encryption", "vulnerabilities",
                "best practices", "compliance", "monitoring"
            ]
        }
        
        # Determine topic category
        topic_lower = topic.lower()
        if "api" in topic_lower:
            relevant_aspects = common_aspects["api"]
        elif any(word in topic_lower for word in ["security", "auth", "encrypt"]):
            relevant_aspects = common_aspects["security"]
        else:
            relevant_aspects = common_aspects["default"]
        
        # Find missing aspects
        covered_lower = [aspect.lower() for aspect in covered_aspects]
        missing = [
            aspect for aspect in relevant_aspects 
            if not any(aspect in covered for covered in covered_lower)
        ]
        
        return missing
    
    def _generate_recommendations(
        self, 
        topic: str, 
        missing_aspects: List[str], 
        result_count: int
    ) -> List[str]:
        """Generate recommendations for improving knowledge base completeness."""
        recommendations = []
        
        if result_count == 0:
            recommendations.append(f"Add foundational documentation about {topic}")
        elif result_count < 3:
            recommendations.append(f"Expand documentation coverage for {topic}")
        
        if missing_aspects:
            recommendations.append(
                f"Consider adding information about: {', '.join(missing_aspects[:3])}"
            )
        
        if result_count > 0:
            recommendations.append("Ensure existing documentation is up-to-date and comprehensive")
        
        recommendations.append("Consider adding practical examples and use cases")
        
        return recommendations